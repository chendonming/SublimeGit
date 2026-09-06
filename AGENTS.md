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
- **Background failures render inside the panel, not just the console** — every
  `err` path calls `views/common.record_error` (stores `state["error"]` with a
  friendly one-liner + raw git stderr) and re-renders; panels draw it via
  `common.error_block` as a red banner (`markup.deleted.diff`, stderr truncated
  to `ERROR_DETAIL_MAX` lines). The banner clears on the next successful refresh.
  A new async operation must follow this pattern — status-bar/console-only errors
  are a bug the user explicitly rejected.
- **Panel views are scratch + read-only; git runs read-only with
  `GIT_OPTIONAL_LOCKS=0`** — except five explicit write paths reached only
  from user action in the Changes panel: the commit flow
  (`Repository.stage_files` + `Repository.commit`), selection-based staging
  (`shift+S` = `Repository.stage_files` for the checked unstaged/untracked
  rows via `paths_to_stage`; `s` = `Repository.unstage_files` =
  `reset HEAD -- <paths>` for the checked staged rows, or
  `rm --cached` on an unborn branch — index-only, the worktree is never
  touched; rename rows must pass old and new path; each direction skips rows
  in the non-matching group so a mixed selection is safe, and after the op
  `state["selected"]` keys migrate with the files to their new `where`),
  `Repository.push` (adds
  `-u <first-remote> <branch>` when the branch has no upstream),
  `Repository.pull`, whose mode comes from the `pull_mode` setting —
  `"rebase"` (default, `git pull --rebase`) or `"ff-only"`; rebase pull is
  user-chosen: on conflicts it leaves the repo mid-rebase, surfaced by the
  in-panel error banner pointing at `git rebase --continue/--abort`, and
  plain merge is still never offered — and `Repository.undo_last_commit`
  (soft `reset --soft HEAD~1`, refused when HEAD is reachable from any
  remote; the parentless root commit goes through `update-ref -d HEAD`).
  Network ops use the
  `git_network_timeout` setting (default 120s, not `git_timeout`), and
  `GIT_TERMINAL_PROMPT=0` makes missing credentials fail fast instead of
  hanging a worker thread. Working-tree files are never touched except by a
  fast-forward pull. Checkbox selection (`state["selected"]`, keyed by
  `(where, path)`) is UI state, deliberately separate from git's staged split;
  `paths_to_stage` skips staged rows (adding the worktree copy could stage
  unseen changes), and callers must pass a non-empty path list — a bare
  `git add -A --` stages the whole tree.
- **The Changes panel's first list row is the ALL root** (rendered whenever
  there are files, row number in `state["root_row"]`): `space` on it toggles
  every file, `a`/`shift+a` select all/none. Its checkbox is `☑` when all
  files are checked, `▣` (`markup.changed.diff`) when some are, `☐` otherwise.
  Lookup order for a cursor row: `commit_rows` → `root_row` → `rows`.
- **The Changes panel's Push/Pull/Undo toolbar is a `LAYOUT_BLOCK` phantom pinned
  at Region(0, 0)**, erased and re-added on every render. Phantoms occupy
  layout space but not buffer positions, so all row/col math is unaffected.
  The Undo button is drawn dim while HEAD is on a remote (derived from
  `state["sample"]` being empty — sample non-empty implies HEAD unpushed).
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
  for new renders. Never capture an `except ... as` name in a deferred callback:
  Python deletes it when the except block exits, so the callback dies with
  "free variable referenced before assignment" and never runs (run_bg rebinds to a
  plain local first — this bug once silenced every background error).

## Git parsing facts (verified on git 2.46 — re-verify before "fixing")

- `status --porcelain=v1 -z`: rename records are `XY NEWPATH<NUL>OLDPATH`.
- `status --porcelain=v1 -z -b`: the branch header is the first NUL record —
  `## NAME...UPSTREAM [ahead N, behind M]`, `[gone]` when the upstream was
  deleted remotely, `## HEAD (no branch)` when detached.
- "Unpushed" = reachable from HEAD but from no remote-tracking ref
  (`git rev-list HEAD --not --remotes`); comparing only against `@{upstream}`
  would falsely flag commits already pushed to other remote branches.
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
