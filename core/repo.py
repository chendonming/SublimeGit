"""Repository-level read-only operations and git output parsers.

This module is pure logic + git CLI calls, no Sublime imports, so the
parsers are unit-testable with plain python3 (see tests/).
"""

import os

from SublimeGit.core import git_runner
from SublimeGit.core.models import Branch, BranchState, Commit, FileHistoryItem, GitFile

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

    def head(self):
        """Full sha of HEAD, or "" when HEAD is unborn."""
        rc, out, _ = git_runner.run_sync(self.root, ["rev-parse", "HEAD"])
        return out.decode("utf-8", "replace").strip() if rc == 0 else ""

    def head_short(self):
        rc, out, _ = git_runner.run_sync(self.root, ["rev-parse", "--short", "HEAD"])
        if rc != 0:
            return ""
        return out.decode("utf-8", "replace").strip()

    # -- status -----------------------------------------------------------

    def status(self):
        """One `git status -z -b` call → (BranchState|None, [GitFile])."""
        out = git_runner.run_ok(self.root, [
            "status", "--porcelain=v1", "-z", "-b", "--untracked-files=normal"])
        return parse_status_full(out)

    def status_files(self):
        return self.status()[1]

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

    # -- remote state ------------------------------------------------------
    # Read-only ref inspection; these define what "already on a remote" means.

    def has_remotes(self):
        rc, out, _ = git_runner.run_sync(self.root, ["remote"])
        return rc == 0 and bool(out.strip())

    def unpushed(self):
        """SHAs reachable from HEAD but from no remote-tracking ref — exactly
        what the next `git push` would publish. Empty when HEAD is unborn.

        "On a remote" means reachable from ANY refs/remotes entry: comparing
        only against @{upstream} would falsely flag commits that were pushed
        to some other remote branch.
        """
        rc, out, _ = git_runner.run_sync(
            self.root, ["rev-list", "HEAD", "--not", "--remotes"])
        if rc != 0:
            return set()
        return set(out.decode("utf-8", "replace").split())

    def unpushed_log(self, limit=8):
        """Newest-first Commits for unpushed(), capped for list rendering."""
        rc, out, _ = git_runner.run_sync(
            self.root, ["log", "-n", str(limit), "--pretty=format:" + LOG_FORMAT,
                        "HEAD", "--not", "--remotes"])
        return parse_log(out) if rc == 0 else []

    def remote_ref_tips(self):
        """{full sha: [remote branch, …]} for commits a remote ref points at.

        Symbolic HEAD refs (refs/remotes/<name>/HEAD) are filtered out — they
        duplicate the default branch's tip as a bare "<name>" label.
        """
        rc, out, _ = git_runner.run_sync(self.root, [
            "for-each-ref", "refs/remotes",
            "--format=%(objectname)%00%(refname)"])
        tips = {}
        if rc == 0:
            for line in out.decode("utf-8", "replace").split("\n"):
                if "\x00" not in line:
                    continue
                sha, ref = line.split("\x00", 1)
                if not sha or not ref.startswith("refs/remotes/"):
                    continue
                name = ref[len("refs/remotes/"):]
                if name.endswith("/HEAD"):
                    continue
                if name:
                    tips.setdefault(sha, []).append(name)
        return tips

    # -- push & pull -------------------------------------------------------
    # Explicit network write paths, reached only from the Changes panel's
    # Push/Pull actions. pull's mode comes from the `pull_mode` setting
    # ("rebase" default / "ff-only"); plain merge is never offered.

    def push(self):
        """Push the current branch; -u <first-remote> on the first push."""
        branch = self._branch_for_sync("push")
        rc, _, _ = git_runner.run_sync(
            self.root, ["rev-parse", "--abbrev-ref", branch + "@{upstream}"])
        args = ["push"]
        if rc != 0:
            args = ["push", "-u", self._default_remote(), branch]
        return self._run_network(args)

    def pull(self):
        """Pull the current branch's upstream. Mode from the `pull_mode`
        setting: "rebase" (default) runs `git pull --rebase`; "ff-only"
        runs `git pull --ff-only` and refuses a divergence."""
        branch = self._branch_for_sync("pull")
        rc, _, _ = git_runner.run_sync(
            self.root, ["rev-parse", "--abbrev-ref", branch + "@{upstream}"])
        if rc != 0:
            raise git_runner.GitError(
                ["pull"], 1,
                "branch '{}' has no upstream to pull from".format(branch))
        mode = git_runner.get_setting("pull_mode", "rebase")
        flag = "--rebase" if mode == "rebase" else "--ff-only"
        return self._run_network(["pull", flag])

    def _branch_for_sync(self, op):
        branch = self.current_branch()
        if branch in ("", "?", "HEAD"):
            if self._rebase_in_progress():
                raise git_runner.GitError(
                    [op], 1,
                    "a rebase is in progress — finish it with "
                    "`git rebase --continue` or `--abort` in a terminal")
            raise git_runner.GitError(
                [op], 1, "detached HEAD — check out a branch first")
        return branch

    def _rebase_in_progress(self):
        """True while a rebase (merge or apply backend) is mid-flight."""
        for name in ("rebase-merge", "rebase-apply"):
            rc, out, _ = git_runner.run_sync(
                self.root, ["rev-parse", "--git-path", name])
            if rc == 0:
                path = out.decode("utf-8", "replace").strip()
                if path and os.path.exists(os.path.join(self.root, path)):
                    return True
        return False

    def _default_remote(self):
        rc, out, _ = git_runner.run_sync(self.root, ["remote"])
        names = out.decode("utf-8", "replace").split()
        if rc != 0 or not names:
            raise git_runner.GitError(
                ["push"], 1, "no remote configured — add one with git remote add")
        return names[0]

    def _run_network(self, args):
        timeout = git_runner.get_setting("git_network_timeout", 120)
        rc, out, err = git_runner.run_sync(self.root, args, timeout)
        if rc != 0:
            raise git_runner.GitError(args, rc, err.decode("utf-8", "replace"))
        # push/pull print their human-readable result on stderr
        lines = [ln.strip() for ln
                 in (out + err).decode("utf-8", "replace").splitlines() if ln.strip()]
        return lines[-1] if lines else "done"

    # -- undo last commit --------------------------------------------------
    # Local history write path for the Changes panel's Undo action. Soft
    # reset only: the commit disappears, its changes stay in the index.

    def undo_last_commit(self):
        """Drop the newest commit, keeping its changes staged.

        Refuses when HEAD is reachable from a remote — undoing a pushed
        commit would rewrite published history. The root commit has no
        parent, so it is undone with `update-ref -d HEAD` (the branch goes
        back to unborn, the index keeps everything staged).
        """
        head = self.head()
        if not head:
            raise git_runner.GitError(["reset"], 1, "no commits to undo")
        if head not in self.unpushed():
            raise git_runner.GitError(
                ["reset"], 1,
                "HEAD is already on the remote — undoing it would rewrite pushed history")
        rc, _, _ = git_runner.run_sync(self.root, ["rev-parse", "HEAD~1"])
        args = ["reset", "--soft", "HEAD~1"] if rc == 0 else ["update-ref", "-d", "HEAD"]
        rc, out, err = git_runner.run_sync(self.root, args)
        if rc != 0:
            raise git_runner.GitError(args, rc, err.decode("utf-8", "replace"))
        return args

    # -- branches ----------------------------------------------------------
    # Branch switching, the sixth explicit write path: plain `git checkout`.
    # Without -f git refuses when the switch would overwrite uncommitted
    # changes — the failure surfaces in the panel banner, nothing is forced.

    def branches(self):
        """Local branches, most recently committed first, HEAD marked."""
        out = git_runner.run_ok(self.root, [
            "for-each-ref", "refs/heads", "--sort=-committerdate",
            "--format=%(HEAD)%00%(refname:short)%00%(objectname:short)"
            "%00%(contents:subject)"])
        return parse_branches(out)

    def checkout(self, branch):
        """Check out a local branch; returns git's human-readable last line
        ("Switched to branch …"), which lands on the status bar."""
        args = ["checkout", branch]
        rc, out, err = git_runner.run_sync(self.root, args)
        if rc != 0:
            raise git_runner.GitError(args, rc, err.decode("utf-8", "replace"))
        # checkout prints "Switched to branch 'x'" on stderr
        lines = [ln.strip() for ln
                 in (out + err).decode("utf-8", "replace").splitlines() if ln.strip()]
        return lines[-1] if lines else "done"

    # -- staging & commit --------------------------------------------------
    # The plugin's explicit commit write path, reached solely from the
    # commit flow in the Changes panel; everything else stays read-only.

    def stage_files(self, paths):
        """`git add -A --` the named paths: stages adds/mods/deletes/renames."""
        git_runner.run_ok(self.root, ["add", "-A", "--"] + list(paths))

    def unstage_files(self, paths):
        """Restore the index entries of paths to HEAD (`git reset HEAD --`).

        Index-only: the working tree is never touched. On an unborn branch
        there is no HEAD to reset to, so the staged adds are removed with
        `git rm --cached` instead (the files become untracked).
        """
        paths = list(paths)
        if not paths:
            return
        if self.head():
            git_runner.run_ok(self.root, ["reset", "HEAD", "--"] + paths)
        else:
            git_runner.run_ok(self.root, ["rm", "--cached", "--"] + paths)

    def commit(self, message):
        """Commit the current index; returns the raw git output (short sha line)."""
        out = git_runner.run_ok(self.root, ["commit", "-m", message])
        return out.decode("utf-8", "replace").strip()


def parse_status_full(data):
    """Parse `git status --porcelain=v1 -z -b` into (BranchState|None, files).

    The -b branch header is the first NUL record ("## NAME...UPSTREAM …");
    detached HEAD is "## HEAD (no branch)" and parses to None.
    """
    tokens = data.split(b"\x00")
    branch = None
    if tokens and tokens[0].startswith(b"##"):
        branch = parse_branch_line(tokens[0].decode("utf-8", "replace"))
        tokens = tokens[1:]
    return branch, parse_status_tokens(tokens)


def parse_branch_line(line):
    """Parse the "## " branch header of `git status -b --porcelain=v1`.

    Forms (verified on git 2.46):
      "## main"                                 — no upstream
      "## main...origin/main"                   — in sync
      "## main...origin/main [ahead 1, behind 2]"
      "## main...origin/main [gone]"            — upstream deleted remotely
      "## No commits yet on main"               — unborn branch
    Returns None for detached HEAD ("## HEAD (no branch)") or junk.
    """
    if not line.startswith("## "):
        return None
    body = line[3:].strip()
    if not body or body.startswith("HEAD"):
        return None
    if body.startswith("No commits yet on "):
        return BranchState(name=body[len("No commits yet on "):].strip())
    name, _, rest = body.partition("...")
    state = BranchState(name=name.strip())
    upstream, _, flags = rest.partition(" [")
    state.upstream = upstream.strip()
    for part in flags.rstrip("]").split(","):
        part = part.strip()
        if part == "gone":
            state.gone = True
        elif part.startswith("ahead"):
            state.ahead = _trailing_int(part)
        elif part.startswith("behind"):
            state.behind = _trailing_int(part)
    return state


def _trailing_int(text):
    try:
        return int(text.split()[-1])
    except (IndexError, ValueError):
        return 0


def parse_branches(data):
    """Parse `for-each-ref refs/heads` output into Branch rows.

    %(HEAD) is "*" on the checked-out branch and a space otherwise (detached
    HEAD marks nothing); fields are NUL-separated, one branch per line.
    """
    branches = []
    for line in data.decode("utf-8", "replace").split("\n"):
        if "\x00" not in line:
            continue
        head, name, short, subject = (line.split("\x00") + ["", ""])[:4]
        if not name:
            continue
        branches.append(Branch(name=name, current=head.strip() == "*",
                               short=short, subject=subject))
    return branches


def parse_status(data):
    """Parse `git status --porcelain=v1 -z` into GitFile entries.

    Rename records are "XY NEWPATH NUL OLDPATH" (verified on git 2.46).
    A file that is both staged and unstaged yields two entries, matching how
    VS Code presents them. -b branch header records are ignored.
    """
    return parse_status_tokens(data.split(b"\x00"))


def parse_status_tokens(tokens):
    files = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        i += 1
        if not token:
            continue
        if token.startswith(b"##"):
            continue  # -b branch header ("## main...origin/main [ahead 1]")
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
