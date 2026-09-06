"""Git Timeline panel.

The repository's commit history in a scratch view. Rows show short hash +
title only; hovering a row pops up the full commit message (title / body /
trailers) via minihtml. Enter opens the commit's changed-file list; picking
a file opens its diff. Pagination is manual: `m` loads the next page.
"""

import html as html_mod

import sublime

from SublimeGit.core import git_runner
from SublimeGit.core import repo as repo_mod
from SublimeGit.core.models import DiffContext, relative_time
from SublimeGit.views import common, diff_view

KIND = "timeline"


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
        return repo.current_branch(), repo.head_short(), repo.log(limit=page)

    def done(result):
        if not view.is_valid() or common.state(view).get("gen") != gen:
            return
        branch, head, commits = result
        st["commits"] = commits
        st["rows"] = {}
        st["loaded"] = len(commits)
        lines = ["  GIT TIMELINE  ·  {}  ·  HEAD {}".format(branch, head or "-"), ""]
        if not commits:
            lines.append("  no commits yet")
        row = len(lines)
        for c in commits:
            st["rows"][row] = c
            lines.append("  {}  {}".format(c.short, c.title))
            row += 1
        lines += ["", "  ⏎ open commit    m load more    r refresh    (hover for details)"]
        st["footer_row"] = len(lines) - 2
        view.run_command("sublimegit_replace_text", {"text": "\n".join(lines) + "\n"})
        _tint_hashes(view)

    def err(e):
        if view.is_valid():
            view.set_status("sublimegit", "SublimeGit: {}".format(e))

    git_runner.run_bg(work, done, err)


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
        for c in commits:
            shifted[row] = c
            new_rows.append("  {}  {}".format(c.short, c.title))
            row += 1
        st["rows"] = shifted
        st["footer_row"] = footer_row + len(commits)
        st["loaded"] = skip + len(commits)
        view.run_command("sublimegit_insert_at_line",
                         {"row": footer_row, "text": "\n".join(new_rows) + "\n"})
        _tint_hashes(view)
        view.set_status("sublimegit",
                        "SublimeGit: loaded {} more commits".format(len(commits)))

    def err(e):
        if view.is_valid():
            view.set_status("sublimegit", "SublimeGit: {}".format(e))

    git_runner.run_bg(work, done, err)


def _tint_hashes(view):
    st = common.state(view)
    regions = []
    for row, commit in st.get("rows", {}).items():
        start = view.text_point(row, 2)
        regions.append(sublime.Region(start, start + len(commit.short)))
    view.erase_regions("sg-hash")
    if regions:
        view.add_regions("sg-hash", regions, "comment")


def hover(view, point):
    if view.is_popup_visible():
        return
    st = common.state(view)
    commit = st.get("rows", {}).get(view.rowcol(point)[0])
    if commit is None:
        return
    view.show_popup(popup_html(commit),
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


def popup_html(commit):
    esc = html_mod.escape
    absolute = (commit.date_iso or "")[:16].replace("T", " ")
    parts = [
        '<div style="padding: 4px;">',
        '<h2 style="margin-top: 0;">{}</h2>'.format(esc(commit.title) or "(no title)"),
        '<p class="meta">{}</p>'.format(esc("{}  ·  {} ({})".format(
            commit.author, relative_time(commit.date_iso), absolute))),
        '<p class="meta"><a href="diff:{0}">{0}</a></p>'.format(esc(commit.short)),
    ]
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
    commit = common.state(view).get("rows", {}).get(view.rowcol(sels[0].begin())[0])
    if commit:
        view.set_status("sublimegit", "{} · {} · ⏎ open · m more · r refresh".format(
            commit.short, commit.title))
    else:
        view.set_status("sublimegit", "⏎ open commit · m load more · r refresh")
