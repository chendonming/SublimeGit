"""Git Panel — the plugin's main panel (view title "Git Panel").

Lists staged / unstaged / untracked files in a scratch view, one checkbox per
file row (space toggles it). Enter or a double-click opens the side-by-side
diff for the file under the cursor; cmd/ctrl+enter commits the checked files.
Checkboxes mean "selected for the next operation" and stay separate from git's
staged/unstaged split. Diff refs are VS Code-style: staged = HEAD vs INDEX,
unstaged = INDEX vs WORKTREE.

Selection is yazi-style: space toggles the checkbox under the cursor (the
root ALL row toggles everything), `a`/`shift+a` select all/none, then
`shift+S` stages the checked files and `s` unstages them — index-only, the
working tree is never touched. Only rows in the matching group act: staging
skips staged rows (the index already holds what you see), unstaging skips
unstaged/untracked rows, so a mixed selection is always safe.

A phantom toolbar at the top of the panel holds the Push, Pull, Undo and
Branch buttons (shift+P / p / u / b; ⌘⇧K / ⌘⌥P still work; the pull mode comes
from
the `pull_mode` setting —
rebase by default, ff-only optional — and the button label shows which is
active). The header shows the upstream with ↑ahead / ↓behind, and an OUTGOING
section lists local commits no remote-tracking ref contains yet — Enter on
one of those rows opens its changed-file list. Undo soft-resets the newest
unpushed commit (changes return to STAGED; refused once HEAD is on a remote).
`b` lists local branches in a quick panel (current one starred, most recent
first); picking one checks it out — git refuses when the switch would
overwrite uncommitted changes and the refusal shows in the panel banner.

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
CHECK_SOME = "▣"  # root ALL row when only part of the files are checked
ROW_FMT = "  {}  {}  {}"  # checkbox, status letter, display path
CHECK_COL = 2
LETTER_COL = 5
CHECK_SCOPE = "markup.inserted.diff"
OUTGOING_MAX = 8  # outgoing commits listed inline; the rest stay in Timeline
TOOLBAR_KEY = "sg-toolbar"
TOOLBAR_BTN = ('<a href="{href}" style="border: 1px solid '
               'color(var(--foreground) alpha(0.30)); border-radius: 3px; '
               'padding: 2px 12px; text-decoration: none; {style}">'
               "{label}</a>")


def _toolbar_html(can_undo):
    mode = git_runner.get_setting("pull_mode", "rebase")
    pull_label = "↓ Pull·rebase" if mode == "rebase" else "↓ Pull·ff-only"
    # {style} sits last so the dim color overrides the anchor's color below
    dim = "color: color(var(--foreground) alpha(0.35));" if not can_undo else ""
    return ('<div style="padding: 0 0 8px 8px;">'
            + TOOLBAR_BTN.format(href="push", label="↑ Push", style="color: var(--foreground);")
            + "&nbsp;&nbsp;"
            + TOOLBAR_BTN.format(href="pull", label=pull_label, style="color: var(--foreground);")
            + "&nbsp;&nbsp;"
            + TOOLBAR_BTN.format(href="undo", label="↩ Undo", style=dim or "color: var(--foreground);")
            + "&nbsp;&nbsp;"
            + TOOLBAR_BTN.format(href="branch", label="⎇ Branch", style="color: var(--foreground);")
            + "</div>")


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
            common.configure_panel(view, KIND, "Git Panel")
            return view
    view = window.new_file()
    common.configure_panel(view, KIND, "Git Panel")
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

    root_row = None
    if files:
        # the ALL root row: space here selects/deselects every file at once —
        # with staged and unstaged lists coexisting, per-group selection alone
        # makes "act on everything" awkward
        n_sel = sum(1 for f in files if _key(f) in selected)
        mark = (CHECK_ON if n_sel == len(files)
                else CHECK_SOME if n_sel else CHECK_OFF)
        root_row = emit("  {}  ALL  ({}/{})".format(mark, n_sel, len(files)))
        header_rows.append(root_row)

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
    emit("  space select · S stage · s unstage · a/A all/none · ⏎ open · ⌘⏎ commit · P push · p pull · u undo · b branch · r refresh")

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

    view.erase_regions("sg-root")
    if root_row is not None and n_sel:
        # ALL's checkbox: green when everything is checked, amber mid-select
        view.add_regions("sg-root",
                         [sublime.Region(view.text_point(root_row, CHECK_COL),
                                         view.text_point(root_row, CHECK_COL) + 1)],
                         CHECK_SCOPE if n_sel == len(files) else "markup.changed.diff")

    st["rows"] = rows
    st["commit_rows"] = commit_rows
    st["root_row"] = root_row


def _render_toolbar(view):
    """Push/Pull/Undo buttons as a block phantom pinned above the header line."""
    view.erase_phantoms(TOOLBAR_KEY)
    can_undo = bool(common.state(view).get("sample"))  # newest unpushed == HEAD
    view.add_phantom(TOOLBAR_KEY, sublime.Region(0, 0), _toolbar_html(can_undo),
                     sublime.LAYOUT_BLOCK,
                     lambda href: _on_toolbar(view, href))


def _on_toolbar(view, href):
    if not view.is_valid():
        return
    if href == "push":
        push(view)
    elif href == "pull":
        pull(view)
    elif href == "undo":
        undo_commit(view)
    elif href == "branch":
        switch_branch(view)


def open_at_row(view, row):
    st = common.state(view)
    if st.get("root_row") == row:
        view.set_status("sublimegit", "ALL is not a file — space toggles every checkbox")
        return
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
    if st.get("root_row") == row:
        _toggle_all(view)
        return
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


def _toggle_all(view):
    """space on the ALL root row: clear when everything is checked, else check all."""
    st = common.state(view)
    keys = {_key(f) for f in st.get("files") or []}
    if keys and keys <= st.get("selected", set()):
        st["selected"] = set()
    else:
        st["selected"] = keys
    _rerender(view)


def select_all(view):
    """`a`: check every file row (idempotent)."""
    st = common.state(view)
    st["selected"] = {_key(f) for f in st.get("files") or []}
    _rerender(view)


def select_none(view):
    """`shift+a`: clear every checkbox (idempotent)."""
    st = common.state(view)
    st["selected"] = set()
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


def _stage_selection(view, op):
    """`shift+S` stages the checked files, `s` unstages them. Only rows in the
    matching group act: staging skips staged rows (the index already holds
    exactly the version the user is looking at — adding the worktree copy
    could stage unseen changes), unstaging skips unstaged/untracked ones, so
    a mixed selection is always safe. Index-only, never touches the working
    tree; renames cover old and new path."""
    st = common.state(view)
    files = st.get("files") or []
    chosen = [f for f in files if _key(f) in st.get("selected", set())]
    window = view.window()
    root = st.get("root")
    if not window or not root:
        view.set_status("sublimegit", "SublimeGit: no repository bound to this panel")
        return
    if st.get("syncing"):
        view.set_status("sublimegit",
                        "SublimeGit: {} already in progress".format(st["syncing"]))
        return
    if not chosen:
        view.set_status("sublimegit",
                        "no files selected — space toggles a row, a selects all")
        return
    paths = []
    if op == "stage":
        paths = paths_to_stage(chosen)
        if not paths:
            view.set_status("sublimegit",
                            "no unstaged files selected — staged rows are already in the index")
            return
    else:
        for f in chosen:
            if f.where == "staged":
                paths.append(f.path)
                if f.old_path:
                    paths.append(f.old_path)
        if not paths:
            view.set_status("sublimegit",
                            "no staged files selected — s only unstages STAGED rows")
            return

    new_where = "staged" if op == "stage" else "unstaged"
    touched = set(paths)
    n = len(chosen)
    st["syncing"] = op
    view.set_status("sublimegit", "SublimeGit: {}ing {} file{}…".format(
        op, n, "" if n == 1 else "s"))

    def work():
        repo = repo_mod.Repository(root)
        if op == "stage":
            repo.stage_files(paths)
        else:
            repo.unstage_files(paths)

    def done(_):
        st.pop("syncing", None)
        if not view.is_valid():
            return
        # the selection follows the files across the staged/unstaged split
        st["selected"] = {(new_where, p) if p in touched else (w, p)
                          for (w, p) in st.get("selected", set())}
        focus_path = chosen[0].path
        refresh(view, on_done=lambda: _refocus(view, focus_path, new_where))

    def err(e):
        st.pop("syncing", None)
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def stage_selected(view):
    _stage_selection(view, "stage")


def unstage_selected(view):
    _stage_selection(view, "unstage")


def _refocus(view, path, prefer_where):
    """Put the caret on `path`'s row after the async re-render moved it."""
    rows = common.state(view).get("rows", {})
    target = None
    for row in sorted(rows):
        f = rows[row]
        if f.path == path:
            if f.where == prefer_where:
                target = row
                break
            if target is None:
                target = row
    if target is not None:
        view.sel().clear()
        view.sel().add(sublime.Region(view.text_point(target, LETTER_COL)))


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


def undo_commit(view):
    """Undo the newest commit — only while it is unpushed (soft reset).

    The newest entry of the OUTGOING sample is HEAD by construction: if HEAD
    were reachable from a remote, every ancestor would be too and the sample
    would be empty. Repository.undo_last_commit re-validates at run time.
    """
    st = common.state(view)
    window = view.window()
    root = st.get("root")
    sample = st.get("sample") or []
    if not window or not root:
        view.set_status("sublimegit", "SublimeGit: no repository bound to this panel")
        return
    if not sample:
        view.set_status("sublimegit",
                        "nothing to undo — the newest commit is already on the remote")
        return
    if st.get("syncing"):
        view.set_status("sublimegit",
                        "SublimeGit: {} already in progress".format(st["syncing"]))
        return
    head = sample[0]
    if not sublime.ok_cancel_dialog(
            "Undo commit {} — {}?\n\nIts changes return to the STAGED list; "
            "nothing is deleted.".format(head.short, head.title), "Undo"):
        return
    st["syncing"] = "undo"
    view.set_status("sublimegit", "SublimeGit: undoing {}…".format(head.short))

    def work():
        repo_mod.Repository(root).undo_last_commit()

    def done(_):
        st.pop("syncing", None)
        if view.is_valid():
            refresh(view)
        window.status_message(
            "SublimeGit: undid {} — changes are back in STAGED".format(head.short))

    def err(e):
        st.pop("syncing", None)
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def switch_branch(view):
    """`b` / the ⎇ Branch button: pick a local branch in a quick panel and
    check it out. The listing runs in the background; the panel stays
    interactive while it loads. A refused checkout (uncommitted changes in
    the way) renders the in-panel banner like every other write path."""
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

    def work():
        return repo_mod.Repository(root).branches()

    def done(branches):
        if not window.is_valid():
            return
        if not branches:
            view.set_status("sublimegit", "SublimeGit: no local branches to switch to")
            return
        _show_branch_panel(view, window, root, branches)

    def err(e):
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def _show_branch_panel(view, window, root, branches):
    entries = ["* {}  {}".format(b.name, b.subject) if b.current
               else "  {}  {}".format(b.name, b.subject)
               for b in branches]

    def pick(index):
        if index < 0:  # esc — show_quick_panel calls back with -1 on cancel
            return
        b = branches[index]
        if b.current:
            view.set_status("sublimegit", "SublimeGit: already on {}".format(b.name))
            return
        _run_checkout(view, window, root, b)

    window.show_quick_panel(entries, pick, sublime.MONOSPACE_FONT)


def _run_checkout(view, window, root, b):
    st = common.state(view)
    if st.get("syncing"):
        view.set_status("sublimegit",
                        "SublimeGit: {} already in progress".format(st["syncing"]))
        return
    st["syncing"] = "checkout"
    view.set_status("sublimegit", "SublimeGit: switching to {}…".format(b.name))

    def work():
        return repo_mod.Repository(root).checkout(b.name)

    def done(line):
        st.pop("syncing", None)
        if view.is_valid():
            refresh(view)
        window.status_message("SublimeGit: {} — {}".format(line, b.name))

    def err(e):
        st.pop("syncing", None)
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def run_anywhere(window, op):
    """Entry points outside the panel (context menu, command palette from a
    normal view) funnel here: make sure this window's Git Panel exists and is
    focused, then run the same op the panel's own keys run. Keeps the syncing
    guard, the post-op refresh, and the in-panel error banner on one code
    path — write ops never run without the panel to show their result. `op`
    is "push" | "pull" | "branch".
    """
    ops = {"push": push, "pull": pull, "branch": switch_branch}
    view = window.active_view()
    if view and common.is_kind(view, KIND):
        ops[op](view)  # already the panel — same as pressing the key
        return

    def ok(root):
        panel = _ensure_view(window, root)
        window.focus_view(panel)
        refresh(panel)  # fill the view; the op's own done() refreshes again
        ops[op](panel)

    def fail():
        window.status_message("SublimeGit: no git repository found in this window")

    common.resolve_repo(window, on_ok=ok, on_fail=fail)


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
    if st.get("root_row") == row:
        view.set_status("sublimegit",
                        "ALL — space selects/deselects everything · a all · A none")
        return
    f = st.get("rows", {}).get(row)
    if f:
        mark = CHECK_ON if _key(f) in st.get("selected", set()) else CHECK_OFF
        view.set_status("sublimegit",
                        "{} {} · space toggle · ⏎ diff".format(mark, f.display_path))
    else:
        view.set_status("sublimegit", "space select · ⏎ open · P push · p pull · r refresh")
