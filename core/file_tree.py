"""Compressed path tree for the Changes panel's file lists.

Builds display rows from the GitFiles of one group (staged / unstaged /
untracked): the paths go into a trie and every chain of single-child
directories collapses into a single label. A lone `core/repo.py` therefore
renders as one flat row exactly like before, while a new untracked
`.../wechat/` folder with N files renders one directory row plus N short
file rows — deep Java-style prefixes stop repeating on every line.

Directory rows are display-only: the panel keeps checkboxes, status letters
and the diff actions (space / enter / double-click) on file rows alone.
"""

from dataclasses import dataclass
from typing import Optional

DIR = "dir"
FILE = "file"


@dataclass
class TreeRow:
    """One display row for a group's file list."""

    kind: str                        # DIR | FILE
    label: str                       # dir: "a/b/" · file: path under its dir row
    depth: int = 0                   # indentation level
    file: Optional[object] = None    # the GitFile, set on file rows only


class _Node:
    __slots__ = ("children", "file")

    def __init__(self):
        self.children = {}           # path segment -> _Node
        self.file = None             # GitFile, set on a leaf


def build_tree(files):
    """GitFiles of one group -> ordered TreeRows (dirs before files)."""
    root = _Node()
    for f in files:
        node = root
        for segment in f.path.split("/"):
            node = node.children.setdefault(segment, _Node())
        node.file = f
    rows = []
    for name, child in _sorted_kids(root):
        _walk(name, child, 0, rows)
    return rows


def _compress(name, node):
    """Fold single-child directory chains into `name` ("a/b/c" style).

    Stops at a leaf (the file keeps the whole chain as its label) or at a
    directory with 2+ children (that one becomes its own row).
    """
    while node.file is None and len(node.children) == 1:
        child_name, child = next(iter(node.children.items()))
        name = name + "/" + child_name
        node = child
    return name, node


def _sorted_kids(node):
    """Compressed children, directories first, case-insensitive by name."""
    kids = [_compress(name, child) for name, child in node.children.items()]
    kids.sort(key=lambda pair: (pair[1].file is not None, pair[0].lower()))
    return kids


def _walk(name, node, depth, rows):
    name, node = _compress(name, node)
    if node.file is not None:
        label = name
        if node.file.old_path:
            label = "{} -> {}".format(node.file.old_path, label)
        rows.append(TreeRow(FILE, label, depth, node.file))
        if not node.children:
            return
        # a file and a directory cannot share one path in git status; keep
        # both visible rather than dropping the subtree if one ever shows up
    rows.append(TreeRow(DIR, name + "/", depth))
    for child_name, child in _sorted_kids(node):
        _walk(child_name, child, depth + 1, rows)
