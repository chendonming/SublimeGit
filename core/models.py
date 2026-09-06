"""Domain models shared by the git layer and the UI layer."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class GitFile:
    path: str
    old_path: Optional[str] = None
    status: str = "M"        # M A D R C T (U = untracked)
    where: str = "unstaged"  # staged | unstaged | untracked

    @property
    def renamed(self):
        return bool(self.old_path)

    @property
    def display_path(self):
        if self.old_path:
            return "{} -> {}".format(self.old_path, self.path)
        return self.path


def paths_to_stage(files):
    """Paths `git add -A --` needs to bring these GitFiles' worktree state
    into the index.

    staged rows are skipped — the index already holds exactly the version the
    user is looking at; adding the worktree copy could stage unseen changes.
    Renames need old and new path (-A records the deletion of the old name).
    """
    out = []
    for f in files:
        if f.where == "staged":
            continue
        out.append(f.path)
        if f.old_path:
            out.append(f.old_path)
    return list(dict.fromkeys(out))


@dataclass
class Commit:
    hash: str = ""
    short: str = ""
    author: str = ""
    email: str = ""
    date_iso: str = ""
    title: str = ""
    body: str = ""
    trailers: str = ""


@dataclass
class FileHistoryItem:
    commit: Optional[Commit] = None
    status: str = "M"                 # what this commit did to the tracked file
    path: Optional[str] = None        # file path inside this commit (right side)
    old_path: Optional[str] = None    # file path before this commit (left side)


@dataclass
class DiffContext:
    """Everything the unified diff view needs to render one comparison.

    left_spec / right_spec: "empty" | "index" | "worktree" | "<git rev>"
    """

    repo_root: str = ""
    path: str = ""
    old_path: Optional[str] = None
    left_spec: str = "empty"
    right_spec: str = "worktree"
    left_path: Optional[str] = None
    right_path: Optional[str] = None
    left_header: str = ""
    right_header: str = ""
    title: str = ""


def relative_time(iso_date):
    """Turn an ISO timestamp into a short relative label like '3h ago'."""
    try:
        dt = datetime.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return iso_date or ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = int((datetime.now(dt.tzinfo) - dt).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return "{}m ago".format(minutes)
    hours = minutes // 60
    if hours < 24:
        return "{}h ago".format(hours)
    days = hours // 24
    if days < 31:
        return "{}d ago".format(days)
    months = days // 30
    if months < 12:
        return "{}mo ago".format(months)
    return "{}y ago".format(days // 365)
