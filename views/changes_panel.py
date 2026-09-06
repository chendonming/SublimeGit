"""Git Changes panel.

Lists staged / unstaged / untracked files in a scratch view, one checkbox per
file row (space toggles it). Enter or a double-click opens the side-by-side
diff for the file under the cursor; cmd/ctrl+enter commits the checked files.
Checkboxes mean "selected for the next operation" and stay separate from git's
staged/unstaged split. Diff refs are VS Code-style: staged = HEAD vs INDEX,
unstaged = INDEX vs WORKTREE.
"""

import time

import sublime

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import DiffContext, paths_to_stage
from SublimeGit.views import common, diff_view

KIND = "changes"
LETTER_SCOPES = {
    "A": "markup.inserted.diff",
    "U": "markup.inserted.diff",
    "D": "markup.deleted.diff",
}
CHECK_ON, CHECK_OFF = "☑", "☐"
ROW_FMT = "  {}  {}  {}"  # checkbox, status letter, display path
CHECK_COL = 2
LETTER_COL = 5
CHECK_SCOPE = "markup.inserted.diff"


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
            common.configure_panel(view, KIND, "Git Changes")
            return view
    view = window.new_file()
    common.configure_panel(view, KIND, "Git Changes")
    common.state(view)["root"] = root
    return view


def refresh(view, on_done=None):
    # re-assert the keymap flag: panels restored from a previous session carry
    # their settings but not necessarily flags added later
    view.settings().set("sublimegit_changes", True)
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


def _key(f):
    """Selection identity: staged and unstaged rows of one path are separate."""
    return (f.where, f.path)


def _render(view, branch, files):
    st = common.state(view)
    st["files"] = files
    st["branch"] = branch
    selected = st.setdefault("selected", set())
    selected.intersection_update(_key(f) for f in files)  # drop rows gone from status

    rows = {}
    header_rows = []
    checked_rows = []
    lines = []

    def emit(text):
        lines.append(text)
        return len(lines) - 1

    header_rows.append(emit("  GIT CHANGES  ·  {}  ·  {} change{}  ·  {} selected".format(
        branch, len(files), "" if len(files) == 1 else "s", len(selected))))
    emit("")

    for title, where in (("STAGED", "staged"), ("UNSTAGED", "unstaged"),
                         ("UNTRACKED", "untracked")):
        group = [f for f in files if f.where == where]
        if not group:
            continue
        header_rows.append(emit("  {}".format(title)))
        for f in group:
            checked = _key(f) in selected
            row = emit(ROW_FMT.format(
                CHECK_ON if checked else CHECK_OFF, f.status, f.display_path))
            rows[row] = f
            if checked:
                checked_rows.append(row)

    if not rows:
        header_rows.append(emit("  ✓ working tree clean"))
    emit("")
    emit("  space select · a all · ⏎ diff · ⌘⏎ commit · r refresh")

    view.run_command("sublimegit_replace_text", {"text": "\n".join(lines) + "\n"})

    view.erase_regions("sg-head")
    view.add_regions("sg-head",
                     [view.full_line(view.text_point(r, 0)) for r in header_rows],
                     "comment")
    by_scope = {}
    for row, f in rows.items():
        scope = LETTER_SCOPES.get(f.status, "markup.changed.diff")
        start = view.text_point(row, LETTER_COL)
        by_scope.setdefault(scope, []).append(sublime.Region(start, start + 1))
    for scope, regions in by_scope.items():
        view.add_regions("sg-letter:" + scope, regions, scope)
    if checked_rows:
        view.add_regions("sg-check",
                         [sublime.Region(view.text_point(r, CHECK_COL),
                                         view.text_point(r, CHECK_COL) + 1)
                          for r in checked_rows],
                         CHECK_SCOPE)

    st["rows"] = rows


def open_at_row(view, row):
    st = common.state(view)
    f = st.get("rows", {}).get(row)
    if f is None:
        view.set_status("sublimegit", "move the cursor to a file line, then press ⏎")
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


def _cursor_row(view):
    sels = view.sel()
    return view.rowcol(sels[0].begin())[0] if sels else 0


def toggle_at_row(view, row):
    st = common.state(view)
    f = st.get("rows", {}).get(row)
    if f is None:
        view.set_status("sublimegit", "move the cursor to a file line, then press space")
        return
    selected = st.setdefault("selected", set())
    k = _key(f)
    if k in selected:
        selected.discard(k)
    else:
        selected.add(k)
    _rerender(view)


def toggle_all(view):
    st = common.state(view)
    keys = {_key(f) for f in st.get("files") or []}
    if keys and keys <= st.get("selected", set()):
        st["selected"] = set()
    else:
        st["selected"] = keys
    _rerender(view)


def _rerender(view):
    """Redraw from cached git state (toggle path — no git round-trip), then put
    the caret back on its row: the replace command resets it to (0, 0)."""
    row = _cursor_row(view)
    st = common.state(view)
    _render(view, st.get("branch", "?"), st.get("files") or [])
    view.sel().clear()
    view.sel().add(sublime.Region(view.text_point(row, LETTER_COL)))


def commit_selected(view):
    st = common.state(view)
    files = st.get("files") or []
    chosen = [f for f in files if _key(f) in st.get("selected", set())]
    if not chosen:
        view.set_status("sublimegit", "no files selected — space toggles a row, a selects all")
        return
    window = view.window()
    if not window:
        return
    root = st.get("root")
    if not root:
        view.set_status("sublimegit", "no repository bound to this panel")
        return

    def on_done(msg):
        msg = msg.strip()
        if msg:
            _run_commit(view, window, root, chosen, msg)
        else:
            window.status_message("SublimeGit: empty message — commit aborted")

    window.show_input_panel("Commit message:", "", on_done, None, None)


def _run_commit(view, window, root, chosen, message):
    def work():
        repo = repo_mod.Repository(root)
        paths = paths_to_stage(chosen)
        if paths:  # never run bare `git add -A --` (empty pathspec = whole tree)
            repo.stage_files(paths)
        return repo.commit(message)

    def done(out):
        refresh(view)
        window.status_message("SublimeGit: {}".format(
            out.splitlines()[0] if out else "committed"))

    def err(e):
        if not view.is_valid():
            return
        stderr = getattr(e, "stderr", "") or ""
        if "nothing to commit" in stderr:
            view.set_status("sublimegit", "nothing to commit")
        else:
            view.set_status("sublimegit", "SublimeGit: {}".format(e))

    git_runner.run_bg(work, done, err)


def show_hint(view):
    sels = view.sel()
    if not sels:
        return
    st = common.state(view)
    f = st.get("rows", {}).get(view.rowcol(sels[0].begin())[0])
    if f:
        mark = CHECK_ON if _key(f) in st.get("selected", set()) else CHECK_OFF
        view.set_status("sublimegit", "{} {} · space toggle · ⏎ diff".format(mark, f.display_path))
    else:
        view.set_status("sublimegit", "space select · ⏎ open diff · r refresh")
