import os
import sys
import unittest

if "sublime" not in sys.modules:
    # the repo root IS the SublimeGit package, so its parent goes on sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from SublimeGit.core import file_tree
from SublimeGit.core.models import GitFile


def ufile(path):
    return GitFile(path=path, status="U", where="untracked")


def sketch(rows):
    return [(r.kind, r.label, r.depth) for r in rows]


class BuildTreeTest(unittest.TestCase):

    def test_empty_group(self):
        self.assertEqual(file_tree.build_tree([]), [])

    def test_single_file_stays_flat(self):
        # the old flat rendering must survive: one file -> one full-path row
        rows = file_tree.build_tree([ufile("core/repo.py")])
        self.assertEqual(sketch(rows), [(file_tree.FILE, "core/repo.py", 0)])

    def test_untracked_folder_collapses_to_one_dir_row(self):
        files = [ufile("mall-single-app/src/main/java/com/pg/wechat/WxConfig.java"),
                 ufile("mall-single-app/src/main/java/com/pg/wechat/WxService.java")]
        rows = file_tree.build_tree(files)
        self.assertEqual(sketch(rows), [
            (file_tree.DIR, "mall-single-app/src/main/java/com/pg/wechat/", 0),
            (file_tree.FILE, "WxConfig.java", 1),
            (file_tree.FILE, "WxService.java", 1),
        ])
        # file rows carry their GitFile back for the panel's row lookup
        self.assertIs(rows[1].file, files[0])
        self.assertIsNone(rows[0].file)

    def test_branching_directory_keeps_relative_children(self):
        files = [ufile("src/main/a.py"), ufile("src/lib/y.py"), ufile("README.md")]
        rows = file_tree.build_tree(files)
        self.assertEqual(sketch(rows), [
            (file_tree.DIR, "src/", 0),
            (file_tree.FILE, "lib/y.py", 1),
            (file_tree.FILE, "main/a.py", 1),
            (file_tree.FILE, "README.md", 0),
        ])

    def test_dirs_sort_before_files_and_grandchildren_indent(self):
        files = [ufile("src/main/b.py"), ufile("src/main/a.py"),
                 ufile("src/z.py"), ufile("README.md")]
        rows = file_tree.build_tree(files)
        self.assertEqual(sketch(rows), [
            (file_tree.DIR, "src/", 0),
            (file_tree.DIR, "main/", 1),
            (file_tree.FILE, "a.py", 2),
            (file_tree.FILE, "b.py", 2),
            (file_tree.FILE, "z.py", 1),
            (file_tree.FILE, "README.md", 0),
        ])

    def test_case_insensitive_sort(self):
        files = [ufile("src/Zeta/a.py"), ufile("src/z.py")]
        rows = file_tree.build_tree(files)
        self.assertEqual(sketch(rows), [
            (file_tree.DIR, "src/", 0),
            (file_tree.FILE, "z.py", 1),
            (file_tree.FILE, "Zeta/a.py", 1),
        ])

    def test_rename_keeps_old_path_in_label(self):
        f = GitFile(path="app/new.py", old_path="lib/old.py",
                    status="R", where="staged")
        rows = file_tree.build_tree([f])
        self.assertEqual(sketch(rows), [(file_tree.FILE, "lib/old.py -> app/new.py", 0)])
        self.assertIs(rows[0].file, f)

    def test_rename_under_dir_row(self):
        f = GitFile(path="app/util/new.py", old_path="lib/old.py",
                    status="R", where="staged")
        other = GitFile(path="app/readme.md", status="M", where="staged")
        rows = file_tree.build_tree([f, other])
        self.assertEqual(sketch(rows), [
            (file_tree.DIR, "app/", 0),
            (file_tree.FILE, "readme.md", 1),
            (file_tree.FILE, "lib/old.py -> util/new.py", 1),
        ])
        # the row's GitFile keeps the rename context for the diff
        self.assertIs(rows[2].file, f)


if __name__ == "__main__":
    unittest.main()
