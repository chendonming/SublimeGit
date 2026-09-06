"""Event wiring: auto-refresh, hover popups, double-click, status hints."""

import time

import sublime
import sublime_plugin

from SublimeGit.views import changes_panel, common, timeline_panel


class SublimegitEventListener(sublime_plugin.EventListener):

    def on_activated_async(self, view):
        if common.is_kind(view, "changes"):
            st = common.state(view)
            if time.time() - st.get("refreshed_at", 0) > 2.0:
                changes_panel.refresh(view)

    def on_post_save_async(self, view):
        window = view.window()
        if not window:
            return
        for v in window.views():
            if common.is_kind(v, "changes"):
                changes_panel.refresh(v)

    def on_hover(self, view, point, hover_zone):
        if hover_zone not in (sublime.HOVER_TEXT, sublime.HOVER_GUTTER):
            return
        if not common.is_kind(view, "timeline"):
            return
        sublime.set_timeout(lambda: timeline_panel.hover(view, point), 0)

    def on_text_command(self, view, command_name, args):
        # A double-click arrives as drag_select with by="words"; open the row
        # under the cursor once the selection has settled.
        if command_name == "drag_select" and args and args.get("by") == "words":
            if common.kind(view) in ("changes", "timeline"):
                st = common.state(view)
                now = time.time()
                if now - st.get("last_click_open", 0) > 0.4:
                    st["last_click_open"] = now
                    sublime.set_timeout(
                        lambda: view.run_command("sublimegit_open_selection"), 120)
        return None

    def on_selection_modified_async(self, view):
        if common.is_kind(view, "changes"):
            changes_panel.show_hint(view)
        elif common.is_kind(view, "timeline"):
            timeline_panel.show_hint(view)

    def on_close(self, view):
        common.drop_state(view)
