# AGENTS.md — SublimeGit

Sublime Text 4 plugin (Python 3.8 host, pinned by `.python-version`). A read-only Git
UI: Changes panel, Timeline panel, File History quick panel, and a unified
side-by-side diff. The repo root IS the package folder `SublimeGit/` (symlinked into
Packages). Feature docs live in README.md.

## Invariants

- **Command classes live only in top-level `.py` files** (`commands.py`,
  `listeners.py`). Sublime registers `sublime_plugin` command classes solely from
  package-top-level modules; classes defined in `core/` or `views/` are never
  registered and fail silently. `views/common.py` stays free of command classes.
- **`TextCommand.run` always takes `edit`**: `def run(self, edit)`. Omitting it raises
  TypeError on every invocation with no visible symptom. `WindowCommand.run` takes no
  extra argument.
- **Keymap contexts match on flat boolean view settings** — `sublimegit_changes`,
  `sublimegit_timeline`, `sublimegit_diff`. They are set in
  `views/common.configure_panel` and re-asserted at the top of each panel's
  `refresh()`, so panels restored from an older session self-heal on activation.
  Dotted setting names such as `setting.sublimegit.view` do not match keymap contexts.
- **Rendering goes through `SublimegitReplaceTextCommand`**, which resets the
  selection to a caret at (0, 0) after replacing the buffer — `view.replace()` alone
  maps the old selection onto the new text, leaving the whole buffer selected and
  breaking every cursor-row lookup. Row lookups that find no item set a status-bar
  hint instead of failing silently.
- **Panel views are scratch + read-only; git runs read-only with
  `GIT_OPTIONAL_LOCKS=0`** — except the explicit commit flow
  (`Repository.stage_files` + `Repository.commit`), the plugin's single write
  path, reached only from user action in the Changes panel. Working-tree files
  are never touched. Checkbox selection (`state["selected"]`, keyed by
  `(where, path)`) is UI state, deliberately separate from git's staged split;
  `paths_to_stage` skips staged rows (adding the worktree copy could stage
  unseen changes), and callers must pass a non-empty path list — a bare
  `git add -A --` stages the whole tree.
- **`set_layout` cells are index tuples into `cols`/`rows`** — each cell is
  `[col_start, row_start, col_end, row_end]` as *indices*, not fractions. A cell
  whose bottom is `0` with `rows: [0.0, 1.0]` is a zero-height group and blanks
  the window to black. The diff's 2-column layout is `[[0, 0, 1, 1], [1, 0, 2, 1]]`
  (see `views/diff_view._render`).
- **Diff pane scroll sync is a poller, not an event** — Sublime has no
  viewport-changed callback, so `_ScrollSync` (`views/diff_view.py`) polls
  viewport y every ~33 ms while both diff views are alive and mirrors y across
  the pair; x stays per-view. Equal y means equal diff row because both panes
  render the same aligned row list. It self-stops when either view dies. The
  `expected`-write guard is load-bearing: without it the syncer reads its own
  writes as user scrolls and the two panes fight each other.
- **All git I/O is async** through `core/git_runner.run_bg`: git runs on a worker
  thread, results arrive on the UI thread. Every async render bumps a `gen` counter in
  the view's state (`views/common.state`) and drops stale results — keep this pattern
  for new renders.

## Git parsing facts (verified on git 2.46 — re-verify before "fixing")

- `status --porcelain=v1 -z`: rename records are `XY NEWPATH<NUL>OLDPATH`.
- `diff --name-status -z` and `diff-tree -z`: rename records are
  `R100<NUL>OLDPATH<NUL>NEWPATH` — the opposite order from status.
- `diff-tree -m` ignores `--first-parent`; diff merges against `sha^` via
  `git diff sha^ sha` (see `Repository.commit_files`, with a `--root` diff-tree
  fallback for the initial commit).
- `%b` in a pretty format still contains the trailers; `parse_log` strips the
  `%(trailers)` field out of the body so body and footer render separately.

## Dev loop

- Only package-top-level `.py` files hot-reload on save. Edits in `core/` or `views/`
  need a full Sublime restart (quit + reopen) to take effect; resource files
  (`.sublime-keymap`, `.sublime-commands`) hot-reload immediately.
- Tests: `python3 -m unittest discover -s tests`. `core/` imports no sublime module on
  purpose — keep parsers and logic there, keep `views/` thin.
- When a panel misbehaves, open the console (`ctrl+\`): background git failures print
  `SublimeGit: background task failed: ...`.
