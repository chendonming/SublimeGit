import os
import sys
import threading
import time
import unittest
from unittest import mock

if "sublime" not in sys.modules:
    # the repo root IS the SublimeGit package, so its parent goes on sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import GitFile, paths_to_stage, relative_time
from SublimeGit.core.repo import (parse_branch_line, parse_branches,
                                  parse_file_history, parse_log,
                                  parse_name_status, parse_status,
                                  parse_status_full)
from SublimeGit.views.common import friendly_error

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


class ParseBranchLineTest(unittest.TestCase):
    def test_plain_branch_without_upstream(self):
        b = parse_branch_line("## main")
        self.assertEqual((b.name, b.upstream, b.ahead, b.behind, b.gone),
                         ("main", "", 0, 0, False))

    def test_upstream_in_sync(self):
        b = parse_branch_line("## main...origin/main")
        self.assertEqual((b.name, b.upstream), ("main", "origin/main"))
        self.assertEqual((b.ahead, b.behind, b.gone), (0, 0, False))

    def test_ahead_and_behind(self):
        b = parse_branch_line("## main...origin/main [ahead 2, behind 3]")
        self.assertEqual((b.name, b.upstream, b.ahead, b.behind), ("main", "origin/main", 2, 3))

    def test_ahead_only(self):
        b = parse_branch_line("## main...origin/main [ahead 1]")
        self.assertEqual((b.ahead, b.behind), (1, 0))

    def test_behind_only(self):
        b = parse_branch_line("## main...origin/main [behind 7]")
        self.assertEqual((b.ahead, b.behind), (0, 7))

    def test_gone_upstream(self):
        b = parse_branch_line("## main...origin/main [gone]")
        self.assertTrue(b.gone)

    def test_non_numeric_counts_stay_zero(self):
        b = parse_branch_line("## main...origin/main [ahead x]")
        self.assertEqual((b.ahead, b.behind), (0, 0))

    def test_unborn_branch(self):
        b = parse_branch_line("## No commits yet on main")
        self.assertEqual((b.name, b.upstream), ("main", ""))

    def test_detached_head_is_none(self):
        self.assertIsNone(parse_branch_line("## HEAD (no branch)"))

    def test_junk_is_none(self):
        self.assertIsNone(parse_branch_line("something else"))


class ParseStatusFullTest(unittest.TestCase):
    def test_branch_header_and_files(self):
        data = "## main...origin/main [ahead 1]\x00MM a.py\x00".encode("utf-8")
        branch, files = parse_status_full(data)
        self.assertEqual(branch.upstream, "origin/main")
        self.assertEqual(branch.ahead, 1)
        self.assertEqual(len(files), 2)

    def test_detached_header(self):
        branch, files = parse_status_full(b"## HEAD (no branch)\x00 D a.py\x00")
        self.assertIsNone(branch)
        self.assertEqual((files[0].status, files[0].where), ("D", "unstaged"))

    def test_plain_status_without_header_still_parses(self):
        branch, files = parse_status_full(b"?? new.py\x00")
        self.assertIsNone(branch)
        self.assertEqual(files[0].where, "untracked")

    def test_parse_status_tolerates_branch_records(self):
        # -b output fed to the old parser must not produce fake file rows
        files = parse_status(b"## main\x00M  a.py\x00")
        self.assertEqual([f.path for f in files], ["a.py"])


class ParseBranchesTest(unittest.TestCase):
    def test_marks_current_branch_and_keeps_fields(self):
        data = (" \x00dev\x00a1b2c3d\x00dev subject\n"
                "*\x00main\x00d4e5f6a\x00main subject\n").encode("utf-8")
        branches = parse_branches(data)
        self.assertEqual([b.name for b in branches], ["dev", "main"])
        self.assertFalse(branches[0].current)
        self.assertTrue(branches[1].current)
        self.assertEqual(branches[1].short, "d4e5f6a")
        self.assertEqual(branches[1].subject, "main subject")

    def test_detached_head_marks_nothing(self):
        data = " \x00main\x00d4e5f6a\x00subject\n".encode("utf-8")
        branches = parse_branches(data)
        self.assertEqual(len(branches), 1)
        self.assertFalse(branches[0].current)

    def test_skips_blank_and_malformed_lines(self):
        data = b"\n\n garbage \n\x00\x00\x00\n \x00main\x00abc\x00s\n"
        branches = parse_branches(data)
        self.assertEqual([b.name for b in branches], ["main"])

    def test_empty_output(self):
        self.assertEqual(parse_branches(b""), [])


class PushPullTest(unittest.TestCase):
    """Repository.push/pull argv decisions, with git subprocesses mocked out."""

    def _patched(self, upstream_rc=0, remotes=b"origin\n", branch=b"feature\n"):
        calls = []

        def fake_run_sync(cwd, args, timeout=None):
            calls.append(args)
            if args[:2] == ["rev-parse", "--abbrev-ref"]:
                if args[2].endswith("@{upstream}"):
                    return upstream_rc, b"", b""
                return 0, branch, b""
            if args[0] == "remote":
                return 0, remotes, b""
            if args[0] in ("push", "pull"):
                return 0, b"", b"main -> main\n"
            return 0, b"", b""

        patcher = mock.patch("SublimeGit.core.git_runner.run_sync", fake_run_sync)
        return calls, patcher

    def test_push_plain_when_upstream_exists(self):
        calls, patcher = self._patched()
        with patcher:
            line = repo_mod.Repository("/r").push()
        self.assertIn(["push"], calls)
        self.assertEqual(line, "main -> main")

    def test_push_sets_upstream_on_first_remote_when_missing(self):
        calls, patcher = self._patched(upstream_rc=1)
        with patcher:
            repo_mod.Repository("/r").push()
        self.assertIn(["push", "-u", "origin", "feature"], calls)

    def test_push_without_remote_raises(self):
        calls, patcher = self._patched(upstream_rc=1, remotes=b"")
        with patcher:
            with self.assertRaises(git_runner.GitError):
                repo_mod.Repository("/r").push()

    def test_pull_defaults_to_rebase(self):
        calls, patcher = self._patched()
        with patcher:
            repo_mod.Repository("/r").pull()
        self.assertIn(["pull", "--rebase"], calls)

    def test_pull_ff_only_when_configured(self):
        calls, patcher = self._patched()
        with patcher, mock.patch.object(git_runner, "get_setting",
                                        lambda name, default=None: "ff-only"):
            repo_mod.Repository("/r").pull()
        self.assertIn(["pull", "--ff-only"], calls)

    def test_pull_without_upstream_raises(self):
        calls, patcher = self._patched(upstream_rc=1)
        with patcher:
            with self.assertRaises(git_runner.GitError):
                repo_mod.Repository("/r").pull()

    def test_detached_head_refuses_sync(self):
        calls, patcher = self._patched(branch=b"HEAD\n")
        with patcher:
            with self.assertRaises(git_runner.GitError):
                repo_mod.Repository("/r").push()


class BranchSwitchTest(unittest.TestCase):
    """Repository.branches/checkout argv, git subprocesses mocked out."""

    def test_branches_uses_for_each_ref_with_head_marker(self):
        captured = {}

        def fake_run_sync(cwd, args, timeout=None):
            captured["args"] = args
            return 0, b"*\x00main\x00abc\x00s\n", b""

        with mock.patch("SublimeGit.core.git_runner.run_sync", fake_run_sync):
            branches = repo_mod.Repository("/r").branches()
        self.assertEqual(captured["args"][0], "for-each-ref")
        self.assertIn("refs/heads", captured["args"])
        self.assertEqual([b.name for b in branches], ["main"])

    def test_checkout_returns_gits_last_line(self):
        def fake_run_sync(cwd, args, timeout=None):
            return 0, b"", b"Switched to branch 'dev'\n"

        with mock.patch("SublimeGit.core.git_runner.run_sync", fake_run_sync):
            line = repo_mod.Repository("/r").checkout("dev")
        self.assertEqual(line, "Switched to branch 'dev'")

    def test_failed_checkout_raises_git_error(self):
        def fake_run_sync(cwd, args, timeout=None):
            return 1, b"", b"error: Your local changes would be overwritten"

        with mock.patch("SublimeGit.core.git_runner.run_sync", fake_run_sync):
            with self.assertRaises(git_runner.GitError):
                repo_mod.Repository("/r").checkout("dev")


class RunBgTest(unittest.TestCase):
    """run_bg must deliver errors on a deferred callback (as set_timeout does).

    Under plain python3 (sublime=None) _ui runs synchronously INSIDE the
    except block, which is exactly why the `except ... as e` deletion bug
    never showed up here — so these tests defer the callback manually.
    """

    def _deferred_run(self, fn, **kwargs):
        from SublimeGit.core import git_runner

        deferred, threads = [], []
        real_thread = threading.Thread

        def fake_thread(*a, **k):
            t = real_thread(*a, **k)
            threads.append(t)
            return t

        with mock.patch.object(git_runner, "_ui", deferred.append), \
                mock.patch.object(git_runner.threading, "Thread",
                                  side_effect=fake_thread):
            git_runner.run_bg(fn, **kwargs)
            for t in threads:
                t.join(timeout=2)
        time.sleep(0.01)  # let the worker fully exit its except block
        return deferred

    def test_error_delivered_after_except_block_exits(self):
        def boom():
            raise ValueError("boom")

        delivered = []
        deferred = self._deferred_run(boom, on_error=delivered.append)
        self.assertEqual(len(deferred), 1)
        deferred[0]()
        self.assertIsInstance(delivered[0], ValueError)

    def test_result_delivered_on_success(self):
        delivered = []
        deferred = self._deferred_run(lambda: 42, on_done=delivered.append)
        self.assertEqual(len(deferred), 1)
        deferred[0]()
        self.assertEqual(delivered[0], 42)


class FriendlyErrorTest(unittest.TestCase):
    """friendly_error maps git stderr onto actionable one-liners."""

    def test_push_rejection_points_to_terminal_pull(self):
        e = git_runner.GitError(["push"], 1,
                                "! [rejected] master -> master (fetch first)")
        self.assertIn("git pull", friendly_error(e))

    def test_ff_only_refusal(self):
        e = git_runner.GitError(["pull"], 1,
                                "fatal: Not possible to fast-forward, aborting.")
        self.assertIn("diverged", friendly_error(e))

    def test_credential_failure(self):
        e = git_runner.GitError(["push"], 128,
                                "fatal: could not read Username for 'https://x': "
                                "terminal prompts disabled")
        self.assertIn("authentication", friendly_error(e))

    def test_fallback_uses_last_stderr_line(self):
        e = git_runner.GitError(["status"], 128, "hint: a\nfatal: bad object HEAD")
        self.assertEqual(friendly_error(e), "fatal: bad object HEAD")


class UndoCommitTest(unittest.TestCase):
    """Repository.undo_last_commit argv decisions, git subprocesses mocked."""

    def _patched(self, head=b"1" * 40 + b"\n", unpushed=b"1" * 40 + b"\n",
                 has_parent=True):
        calls = []

        def fake_run_sync(cwd, args, timeout=None):
            calls.append(args)
            if args == ["rev-parse", "HEAD"]:
                return 0, head, b""
            if args == ["rev-list", "HEAD", "--not", "--remotes"]:
                return 0, unpushed, b""
            if args == ["rev-parse", "HEAD~1"]:
                return (0 if has_parent else 1), b"", b""
            if args[0] in ("reset", "update-ref"):
                return 0, b"", b""
            return 0, b"", b""

        patcher = mock.patch("SublimeGit.core.git_runner.run_sync", fake_run_sync)
        return calls, patcher

    def test_undo_soft_resets_to_parent(self):
        calls, patcher = self._patched()
        with patcher:
            repo_mod.Repository("/r").undo_last_commit()
        self.assertIn(["reset", "--soft", "HEAD~1"], calls)

    def test_undo_root_commit_deletes_branch_ref(self):
        calls, patcher = self._patched(has_parent=False)
        with patcher:
            repo_mod.Repository("/r").undo_last_commit()
        self.assertIn(["update-ref", "-d", "HEAD"], calls)

    def test_undo_refuses_pushed_head(self):
        calls, patcher = self._patched(unpushed=b"")
        with patcher:
            with self.assertRaises(git_runner.GitError):
                repo_mod.Repository("/r").undo_last_commit()
        self.assertNotIn(["reset", "--soft", "HEAD~1"], calls)

    def test_undo_refuses_unborn_head(self):
        calls, patcher = self._patched(head=b"")
        with patcher:
            with self.assertRaises(git_runner.GitError):
                repo_mod.Repository("/r").undo_last_commit()


class StageUnstageTest(unittest.TestCase):
    """Repository.stage_files / unstage_files argv decisions."""

    def _patched(self, head=b"1" * 40 + b"\n"):
        calls = []

        def fake_run_ok(cwd, args, timeout=None):
            calls.append(args)
            return b""

        def fake_run_sync(cwd, args, timeout=None):
            if args == ["rev-parse", "HEAD"]:
                return 0, head, b""
            return 0, b"", b""

        p1 = mock.patch("SublimeGit.core.git_runner.run_ok", fake_run_ok)
        p2 = mock.patch("SublimeGit.core.git_runner.run_sync", fake_run_sync)
        return calls, p1, p2

    def test_stage_runs_add_dash_a(self):
        calls, p1, p2 = self._patched()
        with p1, p2:
            repo_mod.Repository("/r").stage_files(["a.py"])
        self.assertIn(["add", "-A", "--", "a.py"], calls)

    def test_unstage_uses_reset_head(self):
        calls, p1, p2 = self._patched()
        with p1, p2:
            repo_mod.Repository("/r").unstage_files(["a.py"])
        self.assertIn(["reset", "HEAD", "--", "a.py"], calls)

    def test_unstage_rename_covers_both_paths(self):
        calls, p1, p2 = self._patched()
        with p1, p2:
            repo_mod.Repository("/r").unstage_files(["new.py", "old.py"])
        self.assertIn(["reset", "HEAD", "--", "new.py", "old.py"], calls)

    def test_unstage_on_unborn_branch_removes_from_index(self):
        calls, p1, p2 = self._patched(head=b"")
        with p1, p2:
            repo_mod.Repository("/r").unstage_files(["a.py"])
        self.assertIn(["rm", "--cached", "--", "a.py"], calls)

    def test_unstage_with_empty_paths_is_a_noop(self):
        calls, p1, p2 = self._patched()
        with p1, p2:
            repo_mod.Repository("/r").unstage_files([])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
