import os
import sys
import unittest

if "sublime" not in sys.modules:
    # the repo root IS the SublimeGit package, so its parent goes on sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from SublimeGit.core.diff_engine import align, hunks, split_lines


class SplitLinesTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(split_lines(""), [])

    def test_trailing_newline_is_dropped(self):
        self.assertEqual(split_lines("a\nb\n"), ["a", "b"])

    def test_crlf_normalised(self):
        self.assertEqual(split_lines("a\r\nb\r\n"), ["a", "b"])


class AlignTest(unittest.TestCase):
    def test_equal(self):
        rows = align("a\nb\n", "a\nb\n")
        self.assertEqual([r[0] for r in rows], ["equal", "equal"])

    def test_insert_pads_left(self):
        rows = align("a\n", "a\nnew\n")
        self.assertEqual(rows, [("equal", "a", "a"), ("insert", None, "new")])

    def test_delete_pads_right(self):
        rows = align("a\ngone\n", "a\n")
        self.assertEqual(rows, [("equal", "a", "a"), ("delete", "gone", None)])

    def test_replace_pairs_up_then_pads(self):
        rows = align("1\n2\n3\n", "1\nx\ny\nz\n")
        self.assertEqual(rows[0], ("equal", "1", "1"))
        self.assertEqual(rows[1], ("replace", "2", "x"))
        self.assertEqual(rows[2], ("replace", "3", "y"))
        self.assertEqual(rows[3], ("insert", None, "z"))

    def test_research_example(self):
        # the abc/hello/world/new/foo example from the design doc;
        # difflib picks the cheaper alignment (insert 'new', keep 'world')
        rows = align("abc\nhello\nworld\nfoo\n", "abc\nhello\nnew\nworld\nfoo\n")
        self.assertEqual(rows, [
            ("equal", "abc", "abc"),
            ("equal", "hello", "hello"),
            ("insert", None, "new"),
            ("equal", "world", "world"),
            ("equal", "foo", "foo"),
        ])

    def test_both_empty(self):
        self.assertEqual(align("", ""), [])


class HunksTest(unittest.TestCase):
    def test_no_changes(self):
        self.assertEqual(hunks(align("a\nb\n", "a\nb\n")), [])

    def test_single_change(self):
        rows = align("a\nold\n", "a\nnew\n")
        self.assertEqual(hunks(rows), [(1, 2)])

    def test_adjacent_changed_rows_merge(self):
        # replace padded with an insert reads as one block on screen
        rows = align("1\n2\n3\n", "1\nx\ny\nz\n")
        self.assertEqual([r[0] for r in rows],
                         ["equal", "replace", "replace", "insert"])
        self.assertEqual(hunks(rows), [(1, 4)])

    def test_separate_blocks(self):
        rows = align("a\nb\nc\nd\n", "a\nX\nc\nY\n")
        self.assertEqual(hunks(rows), [(1, 2), (3, 4)])

    def test_delete_and_insert_are_hunks(self):
        self.assertEqual(hunks(align("a\ngone\n", "a\n")), [(1, 2)])
        self.assertEqual(hunks(align("a\n", "a\nnew\n")), [(1, 2)])

    def test_empty_rows(self):
        self.assertEqual(hunks([]), [])


if __name__ == "__main__":
    unittest.main()
