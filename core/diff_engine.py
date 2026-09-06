"""Side-by-side diff alignment built on difflib.SequenceMatcher.

align() produces one row per output line for BOTH sides:

    ("equal",   old_line, new_line)  shown on both sides, untinted
    ("replace", old_line, new_line)  yellow tint on both sides
    ("delete",  old_line, None)      red tint, left side only (right is blank)
    ("insert",  None,     new_line)  green tint, right side only (left is blank)

Padding with None keeps the two buffers the same height, which is what makes
the side-by-side view line up.
"""

from difflib import SequenceMatcher

# Beyond this many lines per side we skip SequenceMatcher (O(n^2)) and fall
# back to a naive line-by-line comparison, so huge generated files can't hang
# the plugin host.
MAX_ALIGN_LINES = 4000


def split_lines(text):
    if text == "":
        return []
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")


def align(old_text, new_text):
    old_lines = split_lines(old_text)
    new_lines = split_lines(new_text)
    rows = []

    if len(old_lines) > MAX_ALIGN_LINES or len(new_lines) > MAX_ALIGN_LINES:
        for i in range(max(len(old_lines), len(new_lines))):
            old = old_lines[i] if i < len(old_lines) else None
            new = new_lines[i] if i < len(new_lines) else None
            if old is None:
                rows.append(("insert", None, new))
            elif new is None:
                rows.append(("delete", old, None))
            elif old == new:
                rows.append(("equal", old, new))
            else:
                rows.append(("replace", old, new))
        return rows

    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                rows.append(("equal", old_lines[i1 + k], new_lines[j1 + k]))
        elif tag == "replace":
            old = old_lines[i1:i2]
            new = new_lines[j1:j2]
            for k in range(max(len(old), len(new))):
                if k < len(old) and k < len(new):
                    rows.append(("replace", old[k], new[k]))
                elif k < len(old):
                    rows.append(("delete", old[k], None))
                else:
                    rows.append(("insert", None, new[k]))
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append(("delete", old_lines[k], None))
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append(("insert", None, new_lines[k]))
    return rows


def hunks(rows):
    """Spans (start, end — end exclusive) of contiguous changed rows.

    Input is align() output in order; the indices refer to that same list, so
    the caller offsets them however it numbers its buffer lines. Adjacent
    changed rows (a replace padded with deletes/inserts, for example) merge
    into one span — they read as a single change block on screen.
    """
    spans = []
    for i, (tag, _old, _new) in enumerate(rows):
        if tag == "equal":
            continue
        if spans and spans[-1][1] == i:
            spans[-1] = (spans[-1][0], i + 1)
        else:
            spans.append((i, i + 1))
    return spans
