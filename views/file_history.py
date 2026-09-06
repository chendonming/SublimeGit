"""Git: File History — a quick panel over `git log --follow` for the active
file. Picking a commit opens its diff in the same side-by-side view used by
the Changes panel; rename tracking keeps old/new paths correct."""

import os

import sublime

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import DiffContext, relative_time
from SublimeGit.views import common, diff_view


def open_for_active_view(window):
    view = window.active_view()
    file_path = view.file_name() if view else None
    if not file_path:
        window.status_message("SublimeGit: save the file to disk first")
        return

    def ok(root):
        # macOS can hand out symlinked paths (/var vs /private/var); normalise
        # both sides or relpath produces bogus "../.." segments
        rel = os.path.relpath(os.path.realpath(file_path), os.path.realpath(root))
        if rel.startswith(".."):
            window.status_message("SublimeGit: file is outside the repository")
            return
        limit = git_runner.get_setting("file_history_limit", 200)

        def work():
            return repo_mod.Repository(root).file_history(rel, limit=limit)

        def done(items):
            if not window.is_valid():
                return
            if not items:
                window.status_message("SublimeGit: no history for {}".format(rel))
                return
            _show_panel(window, root, rel, items)

        def err(e):
            if window.is_valid():
                window.status_message("SublimeGit: {}".format(e))

        git_runner.run_bg(work, done, err)

    def fail():
        window.status_message("SublimeGit: no git repository found for this file")

    common.resolve_repo(window, on_ok=ok, on_fail=fail, prefer_path=file_path)


def _show_panel(window, root, rel, items):
    entries = []
    for it in items:
        entries.append([
            "{}  {}".format(it.commit.short, it.commit.title),
            "{}  ·  {} ({})  ·  {}".format(
                it.commit.author, relative_time(it.commit.date_iso),
                (it.commit.date_iso or "")[:16].replace("T", " "),
                (it.status + " " + it.path).strip()),
        ])

    def pick(index):
        if index < 0:  # esc — show_quick_panel calls back with -1 on cancel
            return
        it = items[index]
        ctx = DiffContext(
            repo_root=root, path=it.path, old_path=it.old_path,
            left_spec="empty" if it.status == "A" else it.commit.hash + "^",
            right_spec="empty" if it.status == "D" else it.commit.hash,
            left_path=it.old_path or it.path, right_path=it.path,
            left_header="EMPTY" if it.status == "A" else it.commit.short + "^",
            right_header="EMPTY" if it.status == "D" else it.commit.short,
            title=rel)
        diff_view.open_diff(window, ctx)

    window.show_quick_panel(entries, pick, sublime.MONOSPACE_FONT)
