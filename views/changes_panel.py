"""Git Changes panel.

Lists staged / unstaged / untracked files in a scratch view, one checkbox per
file row (space toggles it). Enter or a double-click opens the side-by-side
diff for the file under the cursor; cmd/ctrl+enter commits the checked files.
Checkboxes mean "selected for the next operation" and stay separate from git's
staged/unstaged split. Diff refs are VS Code-style: staged = HEAD vs INDEX,
unstaged = INDEX vs WORKTREE.

A phantom toolbar at the top of the panel holds the Push and Pull buttons
(⌘⇧K / ⌘⌥P; pull is fast-forward-only). The header shows the upstream with
↑ahead / ↓behind, and an OUTGOING section lists local commits no
remote-tracking ref contains yet — Enter on one of those rows opens its
changed-file list.

Background failures (refresh / push / pull / commit) render as a red banner
inside the panel, with the raw git stderr below the short message — the
console is not required to see what went wrong. The banner clears on the
next successful refresh.
"""

import time

import sublime

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import DiffContext, paths_to_stage
from SublimeGit.views import common, diff_view, timeline_panel

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
OUTGOING_MAX = 8  # outgoing commits listed inline; the rest stay in Timeline
TOOLBAR_KEY = "sg-toolbar"
TOOLBAR_HTML = (
    '<div style="padding: 0 0 8px 8px;">'
    '<a href="push" style="color: var(--foreground); '
    'border: 1px solid color(var(--foreground) alpha(0.30)); '
    'border-radius: 3px; padding: 2px 12px; text-decoration: none;">'
    "↑ Push</a>"
    "&nbsp;&nbsp;&nbsp;"
    '<a href="pull" style="color: var(--foreground); '
    'border: 1px solid color(var(--foreground) alpha(0.30)); '
    'border-radius: 3px; padding: 2px 12px; text-decoration: none;">'
    "↓ Pull</a>"
    "</div>")


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
        branch, files = repo.status()
        has_remote = repo.has_remotes()
        unpushed = repo.unpushed() if has_remote else set()
        sample = repo.unpushed_log(limit=OUTGOING_MAX) if unpushed else []
        return branch, files, has_remote, unpushed, sample

    def done(result):
        if not view.is_valid() or common.state(view).get("gen") != gen:
            return
        branch, files, has_remote, unpushed, sample = result
        st.pop("error", None)  # a successful refresh clears the error banner
        _render(view, branch, files, has_remote, unpushed, sample)
        common.state(view)["refreshed_at"] = time.time()
        if on_done:
            on_done()

    def err(e):
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def _key(f):
    """Selection identity: staged and unstaged rows of one path are separate."""
    return (f.where, f.path)


def _remote_note(branch, has_remote):
    """Header segment describing the upstream: name + ahead/behind marks."""
    if branch is None:
        return ""
    if branch.upstream:
        if branch.gone:
            return "  ·  {} (gone)".format(branch.upstream)
        marks = ""
        if branch.ahead:
            marks += " ↑{}".format(branch.ahead)
        if branch.behind:
            marks += " ↓{}".format(branch.behind)
        return "  ·  {}{}".format(branch.upstream, marks)
    if has_remote:
        return "  ·  no upstream"
    return ""


def _render(view, branch, files, has_remote=False, unpushed=frozenset(), sample=()):
    st = common.state(view)
    st["files"] = files
    st["branch"] = branch
    st["has_remote"] = has_remote
    st["unpushed"] = unpushed
    st["sample"] = sample
    selected = st.setdefault("selected", set())
    selected.intersection_update(_key(f) for f in files)  # drop rows gone from status

    err = st.get("error")
    rows = {}
    commit_rows = {}
    outgoing_hash_rows = []
    error_rows = []
    header_rows = []
    checked_rows = []
    lines = []

    def emit(text):
        lines.append(text)
        return len(lines) - 1

    if branch is None and err and not files:
        header_rows.append(emit("  GIT CHANGES"))  # first load failed
    else:
        name = branch.name if branch else "detached HEAD"
        header_rows.append(emit("  GIT CHANGES  ·  {}{}  ·  {} change{}  ·  {} selected".format(
            name, _remote_note(branch, has_remote),
            len(files), "" if len(files) == 1 else "s", len(selected))))
    emit("")

    if err:
        error_rows, hint_rows = common.error_block(emit, err)
        header_rows.extend(hint_rows)
        emit("")

    if sample:
        header_rows.append(emit(
            "  OUTGOING  ·  not on any remote ({})".format(len(unpushed))))
        for c in sample:
            row = emit("  {}  {}".format(c.short, c.title))
            commit_rows[row] = c
            outgoing_hash_rows.append(row)
        if len(unpushed) > len(sample):
            header_rows.append(emit(
                "  … {} more — see Git Timeline".format(len(unpushed) - len(sample))))
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

    if not rows and not err:
        header_rows.append(emit("  ✓ working tree clean"))
    emit("")
    emit("  space select · a all · ⏎ open · ⌘⏎ commit · ⌘⇧K push · ⌘⌥P pull · r refresh")

    view.run_command("sublimegit_replace_text", {"text": "\n".join(lines) + "\n"})
    _render_toolbar(view)

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
    view.erase_regions("sg-chash")
    if outgoing_hash_rows:
        view.add_regions("sg-chash",
                         [sublime.Region(view.text_point(r, 2),
                                         view.text_point(r, 2) + len(commit_rows[r].short))
                          for r in outgoing_hash_rows],
                         "comment")

    view.erase_regions("sg-err")
    if error_rows:
        view.add_regions("sg-err",
                         [view.full_line(view.text_point(r, 0)) for r in error_rows],
                         common.ERROR_SCOPE)

    st["rows"] = rows
    st["commit_rows"] = commit_rows


def _render_toolbar(view):
    """Push/Pull buttons as a block phantom pinned above the header line."""
    view.erase_phantoms(TOOLBAR_KEY)
    view.add_phantom(TOOLBAR_KEY, sublime.Region(0, 0), TOOLBAR_HTML,
                     sublime.LAYOUT_BLOCK,
                     lambda href: _on_toolbar(view, href))


def _on_toolbar(view, href):
    if not view.is_valid():
        return
    if href == "push":
        push(view)
    elif href == "pull":
        pull(view)


def open_at_row(view, row):
    st = common.state(view)
    commit = st.get("commit_rows", {}).get(row)
    if commit is not None:
        timeline_panel.show_commit_files(view.window(), st.get("root"), commit)
        return
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
    _render(view, st.get("branch"), st.get("files") or [],
            st.get("has_remote", False), st.get("unpushed", frozenset()),
            st.get("sample", ()))
    view.sel().clear()
    view.sel().add(sublime.Region(view.text_point(row, LETTER_COL)))


def push(view):
    _sync(view, "push", "pushing")


def pull(view):
    _sync(view, "pull", "pulling")


def _sync(view, op, busy_word):
    """Run Repository.push/pull on a worker thread, then refresh the panel."""
    st = common.state(view)
    window = view.window()
    root = st.get("root")
    if not window or not root:
        view.set_status("sublimegit", "SublimeGit: no repository bound to this panel")
        return
    if st.get("syncing"):
        view.set_status("sublimegit",
                        "SublimeGit: {} already in progress".format(st["syncing"]))
        return
    st["syncing"] = op
    view.set_status("sublimegit", "SublimeGit: {}…".format(busy_word))

    def work():
        return getattr(repo_mod.Repository(root), op)()

    def done(line):
        st.pop("syncing", None)
        if view.is_valid():
            refresh(view)
        window.status_message("SublimeGit: {} — {}".format(op, line))

    def err(e):
        st.pop("syncing", None)
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def _show_error(view, e):
    """Record the failure, show the short line on the status bar, and render
    the full banner (message + git stderr) inside the panel itself."""
    message = common.record_error(view, e)
    view.set_status("sublimegit", "SublimeGit: {}".format(message))
    st = common.state(view)
    if st.get("files") is not None or st.get("branch") is not None:
        _rerender(view)
    else:
        _render(view, None, [], False, frozenset(), ())


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
            return
        _show_error(view, e)

    git_runner.run_bg(work, done, err)


def show_hint(view):
    sels = view.sel()
    if not sels:
        return
    st = common.state(view)
    row = view.rowcol(sels[0].begin())[0]
    commit = st.get("commit_rows", {}).get(row)
    if commit:
        view.set_status("sublimegit",
                        "↑ {} · {} · ⏎ changed files".format(commit.short, commit.title))
        return
    f = st.get("rows", {}).get(row)
    if f:
        mark = CHECK_ON if _key(f) in st.get("selected", set()) else CHECK_OFF
        view.set_status("sublimegit", "{} {} · space toggle · ⏎ diff".format(mark, f.display_path))
    else:
        view.set_status("sublimegit", "space select · ⏎ open · ⌘⇧K push · ⌘⌥P pull · r refresh")
