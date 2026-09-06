"""The unified side-by-side diff view.

Two read-only scratch views in a 2-column layout, aligned by
core.diff_engine and tinted through the color scheme's diff scopes
(markup.inserted/deleted/changed.diff), so it adapts to any theme.
Everything is driven by a DiffContext — working tree diffs, commit diffs and
file-history diffs all render through this one code path.
"""

import json
from dataclasses import asdict

import sublime

from SublimeGit.core import diff_engine, git_runner
from SublimeGit.core.models import DiffContext
from SublimeGit.core.repo import Repository
from SublimeGit.views import common

KIND = "diff"
DIFF_KEY = "sublimegit.diff"
PREV_LAYOUT_KEY = "sublimegit.prev_layout"
HEADER_ROWS = 2  # title line + rule line

SCOPE_INSERTED = "markup.inserted.diff"
SCOPE_DELETED = "markup.deleted.diff"
SCOPE_CHANGED = "markup.changed.diff"
SCOPE_MUTED = "comment"


def open_diff(window, ctx):
    if window is None:
        return
    repo = Repository(ctx.repo_root)

    def work():
        left = repo.content(ctx.left_spec, ctx.left_path or ctx.path)
        right = repo.content(ctx.right_spec, ctx.right_path or ctx.path)
        return left, right

    def done(result):
        _render(window, ctx, result[0], result[1])

    def err(e):
        if window.is_valid():
            window.status_message("SublimeGit: {}".format(e))

    git_runner.run_bg(work, done, err)


def _render(window, ctx, left_bytes, right_bytes):
    if not window.is_valid():
        return
    binary = b"\x00" in left_bytes or b"\x00" in right_bytes
    if binary:
        rows = [("equal",
                 "(binary file — {} bytes)".format(len(left_bytes)),
                 "(binary file — {} bytes)".format(len(right_bytes)))]
    else:
        rows = diff_engine.align(left_bytes.decode("utf-8", "replace"),
                                 right_bytes.decode("utf-8", "replace"))

    left_col = [r[1] if r[1] is not None else "" for r in rows] or [""]
    right_col = [r[2] if r[2] is not None else "" for r in rows] or [""]
    left_header = ctx.left_header or "OLD"
    right_header = ctx.right_header or "NEW"
    rule = "─" * 60
    left_text = "\n".join([left_header, rule] + left_col) + "\n"
    right_text = "\n".join([right_header, rule] + right_col) + "\n"

    close_diff(window, restore_layout=False)
    if window.settings().get(PREV_LAYOUT_KEY) is None:
        window.settings().set(PREV_LAYOUT_KEY, window.layout())
    window.set_layout({
        "cols": [0.0, 0.5, 1.0],
        "rows": [0.0, 1.0],
        # cell = [col_start, row_start, col_end, row_end] as INDICES into
        # cols/rows; bottom must be 1 here or both groups get zero height
        # and the window renders as a black void
        "cells": [[0, 0, 1, 1], [1, 0, 2, 1]],
    })

    left_view = window.new_file()
    right_view = window.new_file()
    window.set_view_index(left_view, 0, 0)
    window.set_view_index(right_view, 1, 0)

    ctx_json = json.dumps(asdict(ctx))
    for view, role, header, text in (
        (left_view, "old", left_header, left_text),
        (right_view, "new", right_header, right_text),
    ):
        common.configure_panel(
            view, KIND,
            "SG · {} · {} ({})".format(ctx.path, header, role),
            gutter=True)
        view.settings().set(DIFF_KEY, {"role": role, "ctx": ctx_json})
        view.run_command("sublimegit_replace_text", {"text": text})
        _tint(view, rows, binary, is_old_side=(role == "old"))

    _ScrollSync(window.id(), left_view, right_view).start()
    window.focus_view(right_view)
    window.status_message("SublimeGit: diff rendered · {} rows".format(len(rows)))


def _tint(view, rows, binary, is_old_side):
    header_regions = [view.full_line(view.text_point(r, 0)) for r in range(HEADER_ROWS)]
    view.add_regions("sg-head", header_regions, SCOPE_MUTED)
    if binary:
        return
    by_scope = {}
    for offset, (tag, old_line, new_line) in enumerate(rows):
        row = HEADER_ROWS + offset
        if is_old_side and tag == "delete":
            scope = SCOPE_DELETED
        elif is_old_side and tag == "replace" and old_line is not None:
            scope = SCOPE_CHANGED
        elif not is_old_side and tag == "insert":
            scope = SCOPE_INSERTED
        elif not is_old_side and tag == "replace" and new_line is not None:
            scope = SCOPE_CHANGED
        else:
            continue
        start = view.text_point(row, 0)
        by_scope.setdefault(scope, []).append(view.full_line(start))
    for scope, regions in by_scope.items():
        view.add_regions("sg-rows:" + scope, regions, scope)


_SCROLL_SYNC = {}  # window id -> the active _ScrollSync for that window


class _ScrollSync:
    """Mirror the two diff panes' viewport y while the diff is open.

    Both panes render the same aligned row list (padding blanks where a side
    has no line), so equal y means equal diff row — no line mapping needed.
    Sublime has no viewport-changed event, so poll every ~2 frames and stop
    as soon as either view dies. x stays per-view; only y is mirrored.
    """

    INTERVAL_MS = 33
    EPSILON = 0.5  # px — sub-pixel jitter must not feed back into a sync loop
    TTL_TICKS = 5  # how long to wait for a viewport write we issued to land

    def __init__(self, window_id, left, right):
        self._key = window_id
        self._pair = (left, right)
        self._last_y = {v.id(): v.viewport_position()[1] for v in self._pair}
        self._expected = {}  # view id -> (y, ticks left) for our own writes

    def start(self):
        _SCROLL_SYNC[self._key] = self
        sublime.set_timeout(self._tick, self.INTERVAL_MS)

    def stop(self):
        _SCROLL_SYNC.pop(self._key, None)

    def _tick(self):
        if _SCROLL_SYNC.get(self._key) is not self:
            return  # replaced by a newer diff in this window
        left, right = self._pair
        if not (left.is_valid() and right.is_valid()):
            self.stop()
            return

        driver = None
        delta = 0.0
        for view in self._pair:
            vid = view.id()
            y = view.viewport_position()[1]
            expected = self._expected.get(vid)
            if expected is not None:
                exp_y, ttl = expected
                if abs(y - exp_y) <= self.EPSILON:
                    self._expected.pop(vid, None)
                    self._last_y[vid] = y  # our own write landed
                    continue
                if ttl > 0:
                    self._expected[vid] = (exp_y, ttl - 1)
                    continue
                self._expected.pop(vid, None)  # never landed; stop waiting
            moved = y - self._last_y[vid]
            if abs(moved) > self.EPSILON and abs(moved) > delta:
                driver, delta = view, abs(moved)
            else:
                self._last_y[vid] = y

        if driver is not None:
            y = driver.viewport_position()[1]
            other = right if driver is left else left
            x, _ = other.viewport_position()
            self._expected[other.id()] = (y, self.TTL_TICKS)
            other.set_viewport_position((x, y))
            self._last_y[driver.id()] = y

        sublime.set_timeout(self._tick, self.INTERVAL_MS)


def close_diff(window, restore_layout=True):
    _SCROLL_SYNC.pop(window.id(), None)
    for view in list(window.views()):
        try:
            if view.settings().get(DIFF_KEY):
                view.close()
        except Exception:
            pass
    if restore_layout:
        previous = window.settings().get(PREV_LAYOUT_KEY)
        if previous:
            try:
                window.set_layout(previous)
            except Exception:
                pass
            window.settings().erase(PREV_LAYOUT_KEY)


def reload_diff(view):
    """Re-render the diff under the cursor from its stored DiffContext."""
    data = view.settings().get(DIFF_KEY)
    window = view.window()
    if not data or not window:
        return
    ctx = DiffContext(**json.loads(data["ctx"]))
    open_diff(window, ctx)
