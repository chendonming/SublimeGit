"""Shared helpers for SublimeGit views: view tagging, in-memory state, and
repo lookup.

Note: no sublime_plugin.Command subclasses live in subdirectory modules —
Sublime only registers commands from the package's top-level .py files, so
they all live in commands.py.
"""

import os

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod

KIND_KEY = "sublimegit.view"  # settings key; value: changes | timeline | diff

ERROR_SCOPE = "markup.deleted.diff"  # red tint for in-panel error banners
ERROR_DETAIL_MAX = 12                # git stderr lines shown before truncating

_STATE = {}
_REPO_CACHE = {}


def kind(view):
    try:
        return view.settings().get(KIND_KEY)
    except Exception:
        return None


def is_kind(view, kind_value):
    return kind(view) == kind_value


def state(view):
    """Per-view in-memory dict; survives only until the view closes."""
    return _STATE.setdefault(view.id(), {})


def drop_state(view):
    _STATE.pop(view.id(), None)


def configure_panel(view, kind_value, name, gutter=False):
    """Make a scratch, read-only panel view that never writes to disk."""
    view.set_name(name)
    view.set_scratch(True)
    view.set_read_only(True)
    s = view.settings()
    s.set(KIND_KEY, kind_value)
    # flat boolean flags are what keymap contexts match on; dotted setting
    # names proved unreliable there
    s.set("sublimegit_" + kind_value, True)
    s.set("gutter", gutter)
    s.set("word_wrap", False)


def resolve_repo(window, on_ok, on_fail=None, prefer_path=None):
    """Find the repository for a window (cached), then call back on the UI thread."""
    cached = _REPO_CACHE.get(window.id())
    if cached and os.path.isdir(cached):
        on_ok(cached)
        return

    candidates = []
    if prefer_path:
        candidates.append(prefer_path if os.path.isdir(prefer_path) else os.path.dirname(prefer_path))
    candidates.extend(window.folders())

    ordered = []
    seen = set()
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)

    def work():
        for c in ordered:
            root = repo_mod.find_repo_root(c)
            if root:
                return root
        return None

    def done(root):
        if root:
            _REPO_CACHE[window.id()] = root
            on_ok(root)
        elif on_fail:
            on_fail()

    git_runner.run_bg(work, done)


def friendly_error(e):
    """Condense a git failure into one actionable line."""
    msg = getattr(e, "stderr", "") or str(e)
    low = msg.lower()
    if "non-fast-forward" in low or "rejected" in low:
        return ("rejected — the remote has commits you don't have; run "
                "`git pull` in a terminal (merge/rebase if diverged), then push again")
    if "conflict" in low or "could not apply" in low:
        return ("pull stopped on rebase conflicts — resolve them in a terminal "
                "(`git rebase --continue` / `--abort`)")
    if "rebase-merge" in low or "rebase in progress" in low:
        return "a rebase is already in progress — finish it in a terminal first"
    if "not possible to fast-forward" in low:
        return ("diverged from upstream — a merge is needed; resolve it in a "
                "terminal, or set \"pull_mode\": \"rebase\" in the settings")
    if "would be overwritten by merge" in low:
        return "pull would overwrite local changes — commit or stash them first"
    if "detached head" in low:
        return "detached HEAD — check out a branch first"
    if "no upstream" in low or "no tracking information" in low:
        return "this branch has no upstream to pull from"
    if "no remote configured" in low:
        return "no remote configured — add one with `git remote add <name> <url>`"
    if ("could not read username" in low or "authentication" in low
            or "permission denied" in low or "publickey" in low
            or "terminal prompts disabled" in low):
        return "authentication failed — check your credential helper / ssh keys"
    if "does not appear to be a git repository" in low or "connection" in low:
        return "remote unreachable — check the remote URL and network"
    lines = [ln for ln in msg.strip().splitlines() if ln.strip()]
    return (lines[-1] if lines else str(e))[:180]


def record_error(view, e):
    """Store a failure in the view state for the in-panel error banner and
    return the short message for the status bar.

    The banner lives until the next successful refresh overwrites it; the
    raw git stderr rides along in the dict so the panel can show the detail
    the console would have printed.
    """
    message = friendly_error(e)
    state(view)["error"] = {
        "message": message,
        "detail": (getattr(e, "stderr", "") or "").strip(),
    }
    return message


def error_block(emit, err):
    """Emit an error banner into a panel's line list.

    emit(text) must append the text and return its row index. Returns
    (error_rows, hint_rows): error_rows get ERROR_SCOPE (red), hint_rows are
    comment-dimmed.
    """
    error_rows = [emit("  ⚠ {}".format(err.get("message") or "error"))]
    detail = [ln.strip() for ln in (err.get("detail") or "").splitlines()
              if ln.strip()]
    for ln in detail[:ERROR_DETAIL_MAX]:
        error_rows.append(emit("      {}".format(ln)))
    if len(detail) > ERROR_DETAIL_MAX:
        error_rows.append(emit("      … {} more lines (see the console)".format(
            len(detail) - ERROR_DETAIL_MAX)))
    hint_rows = [emit("  (press r to refresh and retry)")]
    return error_rows, hint_rows
