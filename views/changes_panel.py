"""Git Changes panel.

Lists staged / unstaged / untracked files in a scratch view. Enter or a
double-click opens the side-by-side diff for the file under the cursor, with
VS Code-style refs: staged = HEAD vs INDEX, unstaged = INDEX vs WORKTREE.
"""

import time

import sublime

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import DiffContext
from SublimeGit.views import common, diff_view

KIND = "changes"
LETTER_SCOPES = {
    "A": "markup.inserted.diff",
    "U": "markup.inserted.diff",
    "D": "markup.deleted.diff",
}


def open_changes(window):
    def ok(root):
        view = _ensure_view(window, root)
        refresh(view)
        window.focus_view(view)

    def fail():
        window.status_message("SublimeGit: no git repository found in this window")

    common.resolve_repo(window, on_ok=ok, on_fail=fail)


def _ensure_view(window, root):
    for view in window.views():
        if common.is_kind(view, KIND) and common.state(view).get("root") == root:
            return view
    view = window.new_file()
    common.configure_panel(view, KIND, "Git Changes")
    common.state(view)["root"] = root
    return view


def refresh(view, on_done=None):
    st = common.state(view)
    root = st.get("root")
    if not root:
        window = view.window()
        if window:
            def rebind(new_root):
                st.setdefault("root", new_root)
                refresh(view)
            common.resolve_repo(window, on_ok=rebind)
        return
    st["gen"] = st.get("gen", 0) + 1
    gen = st["gen"]

    def work():
        repo = repo_mod.Repository(root)
        return repo.current_branch(), repo.status_files()

    def done(result):
        if not view.is_valid() or common.state(view).get("gen") != gen:
            return
        branch, files = result
        _render(view, branch, files)
        common.state(view)["refreshed_at"] = time.time()
        if on_done:
            on_done()

    def err(e):
        if view.is_valid():
            view.set_status("sublimegit", "SublimeGit: {}".format(e))

    git_runner.run_bg(work, done, err)


def _render(view, branch, files):
    st = common.state(view)
    rows = {}
    header_rows = []
    lines = []

    def emit(text):
        lines.append(text)
        return len(lines) - 1

    header_rows.append(emit("  GIT CHANGES  ·  {}  ·  {} change{}".format(
        branch, len(files), "" if len(files) == 1 else "s")))
    emit("")

    for title, where in (("STAGED", "staged"), ("UNSTAGED", "unstaged"),
                         ("UNTRACKED", "untracked")):
        group = [f for f in files if f.where == where]
        if not group:
            continue
        header_rows.append(emit("  {}".format(title)))
        for f in group:
            row = emit("    {}  {}".format(f.status, f.display_path))
            rows[row] = f

    if not rows:
        header_rows.append(emit("  ✓ working tree clean"))
    emit("")
    emit("  ⏎ open diff    r refresh")

    view.run_command("sublimegit_replace_text", {"text": "\n".join(lines) + "\n"})

    view.erase_regions("sg-head")
    view.add_regions("sg-head",
                     [view.full_line(view.text_point(r, 0)) for r in header_rows],
                     "comment")
    by_scope = {}
    for row, f in rows.items():
        scope = LETTER_SCOPES.get(f.status, "markup.changed.diff")
        start = view.text_point(row, 4)
        by_scope.setdefault(scope, []).append(sublime.Region(start, start + 1))
    for scope, regions in by_scope.items():
        view.add_regions("sg-letter:" + scope, regions, scope)

    st["rows"] = rows


def open_at_row(view, row):
    st = common.state(view)
    f = st.get("rows", {}).get(row)
    if f is None:
        return
    diff_view.open_diff(view.window(), _context_for(st.get("root"), f))


def _context_for(root, f):
    """VS Code-style refs: staged = HEAD vs INDEX, unstaged = INDEX vs WORKTREE."""
    if f.where == "untracked":
        return DiffContext(repo_root=root, path=f.path,
                           left_spec="empty", right_spec="worktree",
                           left_header="EMPTY", right_header="WORKING TREE",
                           title=f.display_path)
    if f.where == "staged":
        if f.status == "A":
            left_spec, left_header = "empty", "EMPTY"
        else:
            left_spec, left_header = "HEAD", "HEAD"
        if f.status == "D":
            right_spec, right_header = "empty", "EMPTY"
        else:
            right_spec, right_header = "index", "INDEX (STAGED)"
        return DiffContext(repo_root=root, path=f.path, old_path=f.old_path,
                           left_spec=left_spec, right_spec=right_spec,
                           left_path=f.old_path or f.path, right_path=f.path,
                           left_header=left_header, right_header=right_header,
                           title=f.display_path)
    # unstaged
    if f.status == "D":
        right_spec, right_header = "empty", "EMPTY"
    else:
        right_spec, right_header = "worktree", "WORKING TREE"
    return DiffContext(repo_root=root, path=f.path,
                       left_spec="index", right_spec=right_spec,
                       left_path=f.path, right_path=f.path,
                       left_header="INDEX (STAGED)", right_header=right_header,
                       title=f.display_path)


def show_hint(view):
    sels = view.sel()
    if not sels:
        return
    f = common.state(view).get("rows", {}).get(view.rowcol(sels[0].begin())[0])
    if f:
        view.set_status("sublimegit", "{} · ⏎ diff · r refresh".format(f.display_path))
    else:
        view.set_status("sublimegit", "⏎ open diff · r refresh")
