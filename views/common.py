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
