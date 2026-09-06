"""Repository-level read-only operations and git output parsers.

This module is pure logic + git CLI calls, no Sublime imports, so the
parsers are unit-testable with plain python3 (see tests/).
"""

import os

from SublimeGit.core import git_runner
from SublimeGit.core.models import Commit, FileHistoryItem, GitFile

# hash NUL short NUL author NUL email NUL date NUL subject NUL body NUL trailers RS
LOG_FORMAT = "%H%x00%h%x00%aN%x00%aE%x00%aI%x00%s%x00%b%x00%(trailers:only,unfold)%x1e"
# RS + hash NUL short NUL author NUL email NUL date NUL subject, followed by --name-status lines
FILE_HISTORY_FORMAT = "%x1e%H%x00%h%x00%aN%x00%aE%x00%aI%x00%s"


def find_repo_root(start_path):
    """Return the repo toplevel for a file/dir path, or None (cheap, sync)."""
    if not start_path:
        return None
    base = start_path if os.path.isdir(start_path) else os.path.dirname(start_path)
    if not base:
        return None
    rc, out, _ = git_runner.run_sync(base, ["rev-parse", "--show-toplevel"])
    if rc != 0:
        return None
    return out.decode("utf-8", "replace").strip() or None


class Repository:
    """Read-only facade over one git repository. Never mutates the working tree."""

    def __init__(self, root):
        self.root = root

    # -- identity ---------------------------------------------------------

    def current_branch(self):
        rc, out, _ = git_runner.run_sync(self.root, ["rev-parse", "--abbrev-ref", "HEAD"])
        if rc != 0:
            return "?"
        return out.decode("utf-8", "replace").strip() or "?"

    def head_short(self):
        rc, out, _ = git_runner.run_sync(self.root, ["rev-parse", "--short", "HEAD"])
        if rc != 0:
            return ""
        return out.decode("utf-8", "replace").strip()

    # -- status -----------------------------------------------------------

    def status_files(self):
        out = git_runner.run_ok(self.root, [
            "status", "--porcelain=v1", "-z", "--untracked-files=normal"])
        return parse_status(out)

    # -- content ----------------------------------------------------------

    def content(self, spec, path):
        """Resolve a DiffContext spec to raw bytes.

        spec: "empty" | "index" | "worktree" | "<git rev>"
        """
        if spec == "empty":
            return b""
        if spec == "worktree":
            return self.worktree_bytes(path)
        if spec == "index":
            return self.blob(":" + path)
        return self.blob("{}:{}".format(spec, path))

    def blob(self, rev_path):
        rc, out, _ = git_runner.run_sync(self.root, ["show", rev_path])
        return out if rc == 0 else b""

    def worktree_bytes(self, relpath):
        try:
            with open(os.path.join(self.root, relpath), "rb") as f:
                return f.read()
        except OSError:
            return b""

    # -- history ----------------------------------------------------------

    def log(self, limit=100, skip=0):
        out = git_runner.run_ok(self.root, [
            "log", "-n", str(limit), "--skip", str(skip),
            "--pretty=format:" + LOG_FORMAT,
        ])
        return parse_log(out)

    def file_history(self, path, limit=200):
        out = git_runner.run_ok(self.root, [
            "log", "--follow", "-n", str(limit), "--name-status",
            "--pretty=format:" + FILE_HISTORY_FORMAT, "--", path,
        ])
        return parse_file_history(out, path)

    def commit_files(self, sha):
        """Files touched by a commit, relative to its first parent.

        git diff-tree -m ignores --first-parent (verified on git 2.46), so we
        diff explicitly against <sha>^ and fall back to --root for the very
        first commit.
        """
        rc, out, _ = git_runner.run_sync(
            self.root, ["diff", sha + "^", sha, "--name-status", "-z", "-M"])
        if rc != 0:
            out = git_runner.run_ok(self.root, [
                "diff-tree", "--no-commit-id", "--name-status", "-r", "-z", "-M",
                "--root", sha])
        return parse_name_status(out)

    # -- staging & commit --------------------------------------------------
    # The plugin's only write path, reached solely from the explicit commit
    # flow in the Changes panel; everything else stays read-only.

    def stage_files(self, paths):
        """`git add -A --` the named paths: stages adds/mods/deletes/renames."""
        git_runner.run_ok(self.root, ["add", "-A", "--"] + list(paths))

    def commit(self, message):
        """Commit the current index; returns the raw git output (short sha line)."""
        out = git_runner.run_ok(self.root, ["commit", "-m", message])
        return out.decode("utf-8", "replace").strip()


def parse_status(data):
    """Parse `git status --porcelain=v1 -z` into GitFile entries.

    Rename records are "XY NEWPATH NUL OLDPATH" (verified on git 2.46).
    A file that is both staged and unstaged yields two entries, matching how
    VS Code presents them.
    """
    tokens = data.split(b"\x00")
    files = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token:
            continue
        entry = token.decode("utf-8", "replace")
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        old_path = None
        if x in "RC" or y in "RC":
            if i >= len(tokens):
                break
            old_path = tokens[i].decode("utf-8", "replace")
            i += 1
        if x == "?":
            files.append(GitFile(path=path, status="U", where="untracked"))
            continue
        if x != " ":
            files.append(GitFile(
                path=path, old_path=old_path if x in "RC" else None,
                status=x, where="staged"))
        if y != " ":
            files.append(GitFile(
                path=path, old_path=old_path if y in "RC" else None,
                status=y, where="unstaged"))
    return files


def parse_log(data):
    """Parse the LOG_FORMAT stream into Commit objects."""
    text = data.decode("utf-8", "replace")
    commits = []
    for record in text.split("\x1e"):
        record = record.lstrip("\n")
        if not record.strip():
            continue
        parts = record.split("\x00", 7)
        while len(parts) < 8:
            parts.append("")
        body, trailers = parts[6], parts[7]
        # %b is the raw message body and still contains the trailers; split apart
        if trailers and body.endswith(trailers):
            body = body[: -len(trailers)]
        commits.append(Commit(
            hash=parts[0], short=parts[1], author=parts[2], email=parts[3],
            date_iso=parts[4], title=parts[5],
            body=body.strip("\n"), trailers=trailers.strip("\n")))
    return commits


def parse_name_status(data):
    """Parse `git diff --name-status -z` / diff-tree into (status, path, old_path).

    Rename records are "R100 OLDPATH NUL NEWPATH" (verified on git 2.46) —
    the opposite order from git status --porcelain.
    """
    tokens = data.split(b"\x00")
    entries = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token:
            continue
        head = token.decode("utf-8", "replace")
        if "\t" in head:  # non -z fallback: "M\tpath" / "R100\told\tnew"
            cols = head.split("\t")
            status = cols[0][0]
            if status in "RC" and len(cols) >= 3:
                entries.append((status, cols[2], cols[1]))
            elif len(cols) >= 2:
                entries.append((status, cols[1], None))
            continue
        status = head[0]
        if i >= len(tokens):
            break
        first = tokens[i].decode("utf-8", "replace")
        i += 1
        if status in "RC":
            if i >= len(tokens):
                break
            second = tokens[i].decode("utf-8", "replace")
            i += 1
            entries.append((status, second, first))
        else:
            entries.append((status, first, None))
    return entries


def parse_file_history(data, track_path):
    """Parse `git log --follow --name-status` into FileHistoryItems.

    The walk goes newest -> oldest and keeps the file's current name, which
    flips back to the older name at every rename commit (--follow semantics).
    """
    text = data.decode("utf-8", "replace")
    items = []
    current_path = track_path
    for block in text.split("\x1e")[1:]:
        if not block.strip():
            continue
        lines = block.split("\n")
        parts = lines[0].split("\x00")
        while len(parts) < 6:
            parts.append("")
        commit = Commit(hash=parts[0], short=parts[1], author=parts[2],
                        email=parts[3], date_iso=parts[4], title=parts[5])
        entry = None
        for line in lines[1:]:
            if not line.strip():
                continue
            cols = line.split("\t")
            status = cols[0][0] if cols else ""
            if status in "RC" and len(cols) > 2:
                new_path, old_path = cols[2], cols[1]
            else:
                new_path, old_path = (cols[1] if len(cols) > 1 else ""), None
            if new_path == current_path:
                entry = (status, new_path, old_path)
                break
        if entry is None:
            # --follow occasionally reports commits without an entry (merges);
            # treat them as a plain modify at the current path
            items.append(FileHistoryItem(commit=commit, status="M",
                                         path=current_path, old_path=current_path))
            continue
        status, new_path, old_path = entry
        items.append(FileHistoryItem(commit=commit, status=status,
                                     path=new_path, old_path=old_path))
        if status in "RC" and old_path:
            current_path = old_path
    return items
