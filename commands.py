"""All SublimeGit commands. The actual logic lives in the views modules."""

import sublime_plugin

from SublimeGit.views import changes_panel, common, diff_view, file_history, timeline_panel


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

    def run(self):
        k = common.kind(self.view)
        if k == "changes":
            changes_panel.refresh(self.view)
        elif k == "timeline":
            timeline_panel.refresh(self.view)


class SublimegitOpenSelectionCommand(sublime_plugin.TextCommand):
    """Open the item under the cursor (⏎ / double-click in list panels)."""

    def is_enabled(self):
        return common.kind(self.view) in ("changes", "timeline")

    def run(self):
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

    def run(self):
        timeline_panel.load_more(self.view)


class SublimegitReloadDiffCommand(sublime_plugin.TextCommand):
    """Re-render the focused diff from its stored DiffContext."""

    def is_enabled(self):
        return common.is_kind(self.view, "diff")

    def run(self):
        diff_view.reload_diff(self.view)
