"""Git Timeline panel.

The repository's commit history in a scratch view. Rows show short hash,
author, relative time and title plus a pushed-state marker: ↑ for commits
reachable from no remote-tracking ref, or the remote branch name when a
remote ref points at the commit. Hovering a row pops up the full commit message (title / body /
trailers) via minihtml. Enter opens the commit's changed-file list; picking a
file opens its diff. Pagination is manual: `m` loads the next page.

Background failures render as a red banner inside the panel (message + git
stderr detail), cleared by the next successful refresh.
"""

import html as html_mod

import sublime

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import DiffContext, relative_time
from SublimeGit.views import common, diff_view

KIND = "timeline"
MARK_UNPUSHED_SCOPE = "markup.changed.diff"  # the ↑ marker on unpushed rows
MARK_REF_SCOPE = "comment"                   # the (origin/main) ref label
AUTHOR_W = 12  # author column width; longer names truncate to …
TIME_W = 8     # relative-time column width; "just now" is the widest label


def _fit(text, width):
    """Truncate to `width` with a trailing … , so columns stay aligned."""
    text = text or ""
    return text if len(text) <= width else text[:width - 1] + "…"


def open_timeline(window):
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
            common.configure_panel(view, KIND, "Git Timeline")
            return view
    view = window.new_file()
    common.configure_panel(view, KIND, "Git Timeline")
    common.state(view)["root"] = root
    return view


def refresh(view):
    # re-assert the keymap flag: panels restored from a previous session carry
    # their settings but not necessarily flags added later
    view.settings().set("sublimegit_timeline", True)
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
    page = git_runner.get_setting("log_page_size", 100)
    st["gen"] = st.get("gen", 0) + 1
    gen = st["gen"]
    st["loaded"] = 0

    def work():
        repo = repo_mod.Repository(root)
        has_remote = repo.has_remotes()
        return (repo.current_branch(), repo.head_short(), repo.log(limit=page),
                repo.unpushed() if has_remote else set(),
                repo.remote_ref_tips() if has_remote else {})

    def done(result):
        if not view.is_valid() or common.state(view).get("gen") != gen:
            return
        branch, head, commits, unpushed, tips = result
        st["branch"] = branch
        st["head"] = head
        st["commits"] = commits
        st["unpushed"] = unpushed
        st["tips"] = tips
        st["loaded"] = len(commits)
        st.pop("error", None)  # a successful refresh clears the error banner
        _render(view)

    def err(e):
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def _render(view):
    """Full redraw from cached state; also how the error banner gets drawn."""
    st = common.state(view)
    commits = st.get("commits") or []
    unpushed = st.get("unpushed", set())
    tips = st.get("tips", {})
    err = st.get("error")
    st["rows"] = {}
    lines = []
    error_rows = []

    def emit(text):
        lines.append(text)
        return len(lines) - 1

    if st.get("branch") is None and err and not commits:
        emit("  GIT TIMELINE")  # first load failed — nothing but the banner
    else:
        header = "  GIT TIMELINE  ·  {}  ·  HEAD {}".format(
            st.get("branch", "?"), st.get("head") or "-")
        if unpushed:
            header += "  ·  ↑{} unpushed".format(len(unpushed))
        emit(header)
    emit("")

    if err:
        error_rows, _hint_rows = common.error_block(emit, err)
        emit("")

    if not commits and not err:
        emit("  no commits yet")
    for c in commits:
        st["rows"][emit(_commit_line(c, unpushed, tips))] = c
    emit("")
    emit("  ⏎ open commit    m load more    r refresh    (hover for details)")
    st["footer_row"] = len(lines) - 2
    view.run_command("sublimegit_replace_text", {"text": "\n".join(lines) + "\n"})
    _tint(view)
    view.erase_regions("sg-err")
    if error_rows:
        view.add_regions("sg-err",
                         [view.full_line(view.text_point(r, 0)) for r in error_rows],
                         common.ERROR_SCOPE)


def _show_error(view, e):
    """Record the failure, show the short line on the status bar, and render
    the full banner (message + git stderr) inside the panel itself."""
    message = common.record_error(view, e)
    view.set_status("sublimegit", "SublimeGit: {}".format(message))
    _render(view)


def _marker_text(commit, unpushed, tips):
    """Trailing row marker: ↑ when the commit is on no remote, else the
    (remote branch) label when a remote-tracking ref points at it."""
    if commit.hash in unpushed:
        return "↑"
    names = tips.get(commit.hash)
    if names:
        shown = ", ".join(names[:2])
        if len(names) > 2:
            shown += ", …"
        return "({})".format(shown)
    return ""


def _commit_line(c, unpushed, tips):
    mark = _marker_text(c, unpushed, tips)
    # fixed-width author/time columns: load_more appends rows without
    # redrawing earlier ones, so widths must not depend on the loaded page
    text = "  {}  {}  {}  {}".format(
        c.short,
        _fit(c.author, AUTHOR_W).ljust(AUTHOR_W),
        _fit(relative_time(c.date_iso), TIME_W).ljust(TIME_W),
        c.title)
    return text + "  " + mark if mark else text


def _mark_offset(short_len, title_len):
    """Char offset of the row's trailing pushed-state marker (used by _tint).

    The marker sits two spaces after the title, so the separator counts too."""
    return 2 + short_len + 2 + AUTHOR_W + 2 + TIME_W + 2 + title_len + 2


def load_more(view):
    st = common.state(view)
    root = st.get("root")
    if not root:
        return
    page = git_runner.get_setting("log_page_size", 100)
    skip = st.get("loaded", 0)
    gen = st.get("gen", 0)

    def work():
        return repo_mod.Repository(root).log(limit=page, skip=skip)

    def done(commits):
        if not view.is_valid() or st.get("gen") != gen:
            return
        if not commits:
            view.set_status("sublimegit", "SublimeGit: no more commits")
            return
        footer_row = st.get("footer_row", view.rowcol(view.size())[0])
        rows = st.get("rows", {})
        shifted = {r + len(commits) if r >= footer_row else r: c
                   for r, c in rows.items()}
        row = footer_row
        new_rows = []
        unpushed = st.get("unpushed", set())
        tips = st.get("tips", {})
        for c in commits:
            shifted[row] = c
            new_rows.append(_commit_line(c, unpushed, tips))
            row += 1
        st["rows"] = shifted
        st["commits"] = (st.get("commits") or []) + commits
        st["footer_row"] = footer_row + len(commits)
        st["loaded"] = skip + len(commits)
        view.run_command("sublimegit_insert_at_line",
                         {"row": footer_row, "text": "\n".join(new_rows) + "\n"})
        _tint(view)
        view.set_status("sublimegit",
                        "SublimeGit: loaded {} more commits".format(len(commits)))

    def err(e):
        if view.is_valid():
            _show_error(view, e)

    git_runner.run_bg(work, done, err)


def _tint(view):
    """Colour the short hashes plus the pushed-state markers / ref labels."""
    st = common.state(view)
    unpushed = st.get("unpushed", set())
    tips = st.get("tips", {})
    hashes, marks, refs = [], [], []
    for row, commit in st.get("rows", {}).items():
        start = view.text_point(row, 2)
        hashes.append(sublime.Region(start, start + len(commit.short)))
        mark = _marker_text(commit, unpushed, tips)
        if not mark:
            continue
        mstart = view.text_point(
            row, _mark_offset(len(commit.short), len(commit.title)))
        region = sublime.Region(mstart, mstart + len(mark))
        (marks if commit.hash in unpushed else refs).append(region)
    view.erase_regions("sg-hash")
    view.erase_regions("sg-mark")
    view.erase_regions("sg-ref")
    if hashes:
        view.add_regions("sg-hash", hashes, "comment")
    if marks:
        view.add_regions("sg-mark", marks, MARK_UNPUSHED_SCOPE)
    if refs:
        view.add_regions("sg-ref", refs, MARK_REF_SCOPE)


def hover(view, point):
    if view.is_popup_visible():
        return
    st = common.state(view)
    commit = st.get("rows", {}).get(view.rowcol(point)[0])
    if commit is None:
        return
    unpushed = commit.hash in st.get("unpushed", set())
    view.show_popup(popup_html(commit, unpushed=unpushed),
                    flags=sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                    location=point, max_width=640, max_height=440,
                    on_navigate=lambda href: _navigate(view, href))


def _navigate(view, href):
    if not href.startswith("diff:"):
        return
    sha = href[len("diff:"):]
    st = common.state(view)
    for commit in st.get("commits", []):
        if commit.hash.startswith(sha) or commit.short == sha:
            show_commit_files(view.window(), st.get("root"), commit)
            return


def popup_html(commit, unpushed=False):
    esc = html_mod.escape
    absolute = (commit.date_iso or "")[:16].replace("T", " ")
    parts = [
        '<div style="padding: 4px;">',
        '<h2 style="margin-top: 0;">{}</h2>'.format(esc(commit.title) or "(no title)"),
        '<p class="meta">{}</p>'.format(esc("{}  ·  {} ({})".format(
            commit.author, relative_time(commit.date_iso), absolute))),
        '<p class="meta"><a href="diff:{0}">{0}</a></p>'.format(esc(commit.short)),
    ]
    if unpushed:
        parts.append('<p class="meta">↑ not on any remote — goes out with the next push</p>')
    if commit.body:
        parts.append('<p>{}</p>'.format(esc(commit.body).replace("\n", "<br>")))
    if commit.trailers:
        parts.append('<p class="meta">{}</p>'.format(
            esc(commit.trailers).replace("\n", "<br>")))
    parts.append('<p class="meta">⏎ open commit diff</p>')
    parts.append("</div>")
    return "".join(parts)


def open_commit_at_row(view, row):
    st = common.state(view)
    commit = st.get("rows", {}).get(row)
    if commit is None:
        view.set_status("sublimegit", "move the cursor to a commit line, then press ⏎")
        return
    show_commit_files(view.window(), st.get("root"), commit)


def show_commit_files(window, root, commit):
    if window is None or not root:
        return

    def work():
        return repo_mod.Repository(root).commit_files(commit.hash)

    def done(entries):
        if not window.is_valid():
            return
        if not entries:
            window.status_message(
                "SublimeGit: no file changes in {}".format(commit.short))
            return
        items = []
        for status, path, old_path in entries:
            sub = "{}  {}".format(status, old_path) if old_path else status
            items.append([path, sub])

        def pick(index):
            if index < 0:  # esc — show_quick_panel calls back with -1 on cancel
                return
            status, path, old_path = entries[index]
            ctx = DiffContext(
                repo_root=root, path=path, old_path=old_path,
                left_spec="empty" if status == "A" else commit.hash + "^",
                right_spec="empty" if status == "D" else commit.hash,
                left_path=old_path or path, right_path=path,
                left_header="EMPTY" if status == "A" else commit.short + "^",
                right_header="EMPTY" if status == "D" else commit.short,
                title=path)
            diff_view.open_diff(window, ctx)

        window.show_quick_panel(items, pick, sublime.MONOSPACE_FONT)

    def err(e):
        if window.is_valid():
            window.status_message("SublimeGit: {}".format(e))

    git_runner.run_bg(work, done, err)


def show_hint(view):
    sels = view.sel()
    if not sels:
        return
    st = common.state(view)
    commit = st.get("rows", {}).get(view.rowcol(sels[0].begin())[0])
    if commit:
        extra = " · ↑ unpushed" if commit.hash in st.get("unpushed", set()) else ""
        view.set_status("sublimegit", "{} · {}{} · ⏎ open · m more · r refresh".format(
            commit.short, commit.title, extra))
    else:
        view.set_status("sublimegit", "⏎ open commit · m load more · r refresh")
