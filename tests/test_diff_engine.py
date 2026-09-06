import os
import sys
import unittest

if "sublime" not in sys.modules:
    # the repo root IS the SublimeGit package, so its parent goes on sys.path
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))

from SublimeGit.core.diff_engine import align, split_lines


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


if __name__ == "__main__":
    unittest.main()
