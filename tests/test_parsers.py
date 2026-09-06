import os
import sys
import unittest

if "sublime" not in sys.modules:
    # the repo root IS the SublimeGit package, so its parent goes on sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from SublimeGit.core.models import GitFile, paths_to_stage, relative_time
from SublimeGit.core.repo import (parse_file_history, parse_log,
                                  parse_name_status, parse_status)

RS = "\x1e"
NUL = "\x00"


class ParseStatusTest(unittest.TestCase):
    def test_staged_and_unstaged_split_into_two_entries(self):
        files = parse_status(b"MM a.py\x00")
        self.assertEqual(len(files), 2)
        self.assertEqual((files[0].status, files[0].where), ("M", "staged"))
        self.assertEqual((files[1].status, files[1].where), ("M", "unstaged"))

    def test_untracked(self):
        files = parse_status(b"?? new file.py\x00")
        self.assertEqual(len(files), 1)
        self.assertEqual((files[0].status, files[0].where), ("U", "untracked"))
        self.assertEqual(files[0].path, "new file.py")

    def test_rename_new_path_comes_first(self):
        # verified on git 2.46: "R  NEWPATH\x00OLDPATH\x00"
        files = parse_status(b"R  renamed.txt\x00new.txt\x00")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].path, "renamed.txt")
        self.assertEqual(files[0].old_path, "new.txt")
        self.assertEqual(files[0].where, "staged")

    def test_added_staged(self):
        files = parse_status(b"A  a.py\x00")
        self.assertEqual((files[0].status, files[0].where), ("A", "staged"))

    def test_deleted_unstaged(self):
        files = parse_status(b" D a.py\x00")
        self.assertEqual((files[0].status, files[0].where), ("D", "unstaged"))

    def test_empty_status(self):
        self.assertEqual(parse_status(b""), [])


class ParseLogTest(unittest.TestCase):
    def test_full_record_splits_body_from_trailers(self):
        data = (NUL.join([
            "a" * 40, "abc1234", "Tester", "t@t.com",
            "2026-09-06T16:00:00+08:00", "feat: add thing",
            "body line\n\nSigned-off-by: Tester <t@t.com>\n",
            "Signed-off-by: Tester <t@t.com>\n",
        ]) + RS).encode("utf-8")
        commits = parse_log(data)
        self.assertEqual(len(commits), 1)
        c = commits[0]
        self.assertEqual(c.short, "abc1234")
        self.assertEqual(c.author, "Tester")
        self.assertEqual(c.title, "feat: add thing")
        self.assertEqual(c.body, "body line")
        self.assertEqual(c.trailers, "Signed-off-by: Tester <t@t.com>")

    def test_multiple_records_and_empty_body(self):
        rec = NUL.join(["h" * 40, "h", "A", "a@a",
                        "2026-01-01T00:00:00+00:00", "t", "", ""])
        data = (rec + RS + "\n" + rec + RS).encode("utf-8")
        commits = parse_log(data)
        self.assertEqual(len(commits), 2)

    def test_empty_log(self):
        self.assertEqual(parse_log(b""), [])


class ParseNameStatusTest(unittest.TestCase):
    def test_modify(self):
        self.assertEqual(parse_name_status(b"M\x00a.py\x00"), [("M", "a.py", None)])

    def test_rename_old_path_comes_first(self):
        # verified on git 2.46: "R100\x00OLDPATH\x00NEWPATH\x00"
        self.assertEqual(parse_name_status(b"R100\x00a.txt\x00b.txt\x00"),
                         [("R", "b.txt", "a.txt")])

    def test_add_delete(self):
        self.assertEqual(parse_name_status(b"A\x00n.py\x00D\x00o.py\x00"),
                         [("A", "n.py", None), ("D", "o.py", None)])


class ParseFileHistoryTest(unittest.TestCase):
    def test_rename_walk_flips_tracked_path(self):
        def rec(h, short, subject):
            return RS + NUL.join([h, short, "Tester", "t@t.com",
                                  "2026-09-06T16:00:00+08:00", subject])

        data = (rec("2" * 40, "ccccc22", "edit p.py") + "\nM\tp.py\n"
                + rec("1" * 40, "aaaaa11", "rename q.py to p.py")
                + "\nR100\tq.py\tp.py\n").encode("utf-8")
        items = parse_file_history(data, "p.py")
        self.assertEqual(len(items), 2)
        self.assertEqual((items[0].status, items[0].path), ("M", "p.py"))
        self.assertEqual((items[1].status, items[1].path, items[1].old_path),
                         ("R", "p.py", "q.py"))

    def test_added_commit_has_no_old_path(self):
        def rec(h, short, subject):
            return RS + NUL.join([h, short, "Tester", "t@t.com",
                                  "2026-09-06T16:00:00+08:00", subject])

        data = (rec("1" * 40, "aaaaa11", "add p.py") + "\nA\tp.py\n").encode("utf-8")
        items = parse_file_history(data, "p.py")
        self.assertEqual(items[0].status, "A")
        self.assertIsNone(items[0].old_path)


class RelativeTimeTest(unittest.TestCase):
    def test_recent(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        self.assertEqual(relative_time((now - timedelta(minutes=5)).isoformat()), "5m ago")
        self.assertEqual(relative_time((now - timedelta(hours=3)).isoformat()), "3h ago")
        self.assertEqual(relative_time((now - timedelta(days=2)).isoformat()), "2d ago")

    def test_bad_input_returns_input(self):
        self.assertEqual(relative_time("not-a-date"), "not-a-date")


class PathsToStageTest(unittest.TestCase):
    def test_staged_rows_are_skipped(self):
        paths = paths_to_stage([GitFile(path="a.py", where="staged")])
        self.assertEqual(paths, [])

    def test_unstaged_and_untracked_paths_are_staged(self):
        paths = paths_to_stage([
            GitFile(path="a.py", where="unstaged"),
            GitFile(path="b.py", status="U", where="untracked"),
        ])
        self.assertEqual(paths, ["a.py", "b.py"])

    def test_rename_needs_old_and_new_path(self):
        paths = paths_to_stage([
            GitFile(path="new.py", old_path="old.py", status="R", where="unstaged")])
        self.assertEqual(paths, ["new.py", "old.py"])

    def test_both_rows_of_one_file_deduplicate(self):
        paths = paths_to_stage([
            GitFile(path="a.py", where="staged"),
            GitFile(path="a.py", where="unstaged"),
        ])
        self.assertEqual(paths, ["a.py"])


if __name__ == "__main__":
    unittest.main()
