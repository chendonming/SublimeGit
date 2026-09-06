"""All SublimeGit commands.

Every sublime_plugin command class MUST live in this top-level module (or
another top-level one): Sublime only scans a package's top-level .py files
for command classes, so classes in subdirectory modules are never
registered. The actual logic lives in the views modules.
"""

import sublime
import sublime_plugin

from SublimeGit.views import changes_panel, common, diff_view, file_history, timeline_panel


class SublimegitReplaceTextCommand(sublime_plugin.TextCommand):
    """Replace the whole buffer — how every panel renders itself."""

    def run(self, edit, text=""):
        view = self.view
        read_only = view.is_read_only()
        view.set_read_only(False)
        view.replace(edit, sublime.Region(0, view.size()), text)
        view.set_read_only(read_only)


class SublimegitInsertAtLineCommand(sublime_plugin.TextCommand):
    """Insert text at the start of a line (used to append timeline pages)."""

    def run(self, edit, row=0, text=""):
        view = self.view
        read_only = view.is_read_only()
        view.set_read_only(False)
        view.insert(edit, view.text_point(row, 0), text)
        view.set_read_only(read_only)


class SublimegitOpenChangesCommand(sublime_plugin.WindowCommand):
    """Git: Open Changes — the changed-files panel."""

    def run(self):
        changes_panel.open_changes(self.window)


class SublimegitOpenTimelineCommand(sublime_plugin.WindowCommand):
    """Git: Open Timeline — the commit-history panel."""

    def run(self):
        timeline_panel.open_timeline(self.window)


class SublimegitFileHistoryCommand(sublime_plugin.WindowCommand):
    """Git: File History — history of the active file via quick panel."""

    def run(self):
        file_history.open_for_active_view(self.window)


class SublimegitCloseDiffCommand(sublime_plugin.WindowCommand):
    """Git: Close Diff — close both diff panes and restore the layout."""

    def run(self):
        diff_view.close_diff(self.window)


class SublimegitRefreshViewCommand(sublime_plugin.TextCommand):
    """Refresh the focused panel (`r` in Changes/Timeline views)."""

    def is_enabled(self):
        return common.kind(self.view) in ("changes", "timeline")

    def run(self, edit):
        k = common.kind(self.view)
        if k == "changes":
            changes_panel.refresh(self.view)
        elif k == "timeline":
            timeline_panel.refresh(self.view)


class SublimegitOpenSelectionCommand(sublime_plugin.TextCommand):
    """Open the item under the cursor (⏎ / double-click in list panels)."""

    def is_enabled(self):
        return common.kind(self.view) in ("changes", "timeline")

    def run(self, edit):
        k = common.kind(self.view)
        sels = self.view.sel()
        if k not in ("changes", "timeline") or not sels:
            return
        row = self.view.rowcol(sels[0].begin())[0]
        if k == "changes":
            changes_panel.open_at_row(self.view, row)
        else:
            timeline_panel.open_commit_at_row(self.view, row)


class SublimegitLoadMoreCommand(sublime_plugin.TextCommand):
    """Load the next page of commits (`m` in the Timeline view)."""

    def is_enabled(self):
        return common.kind(self.view) == "timeline"

    def run(self, edit):
        timeline_panel.load_more(self.view)


class SublimegitReloadDiffCommand(sublime_plugin.TextCommand):
    """Re-render the focused diff from its stored DiffContext."""

    def is_enabled(self):
        return common.is_kind(self.view, "diff")

    def run(self, edit):
        diff_view.reload_diff(self.view)
