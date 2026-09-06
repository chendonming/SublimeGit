"""Async subprocess runner for the git CLI.

Design rules:
- argv is always a list, never shell=True
- GIT_OPTIONAL_LOCKS=0 keeps git from writing the index for read-only
  commands, so the working directory is never touched
- git runs on worker threads; UI callbacks are marshalled back with
  sublime.set_timeout
"""

import os
import shutil
import subprocess
import threading

try:
    import sublime
except ImportError:  # running under plain python3 (unit tests)
    sublime = None


class GitError(Exception):
    """Raised when a git command exits non-zero."""

    def __init__(self, args, returncode, stderr):
        self.args_list = list(args)
        self.returncode = returncode
        self.stderr = stderr
        super().__init__("git {} failed ({}): {}".format(
            " ".join(self.args_list), returncode, stderr.strip()))


def get_setting(name, default=None):
    if sublime is None:
        return default
    return sublime.load_settings("SublimeGit.sublime-settings").get(name, default)


def git_binary():
    configured = (get_setting("git_path") or "").strip()
    if configured:
        return configured
    return shutil.which("git") or "git"


def run_sync(cwd, args, timeout=None):
    """Run git in cwd; return (returncode, stdout_bytes, stderr_bytes).

    Never raises on non-zero rc — callers decide what counts as an error.
    """
    timeout = timeout or get_setting("git_timeout", 20)
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    cmd = [git_binary(), "-C", cwd] + list(args)
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, env=env)
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out or b"", err or b""
    except FileNotFoundError:
        return 127, b"", b"git executable not found (check the git_path setting)"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return 124, b"", ("timeout after {}s: git {}".format(
            timeout, " ".join(args))).encode("utf-8")
    except OSError as e:
        return 126, b"", str(e).encode("utf-8")


def run_ok(cwd, args, timeout=None):
    """Run git and return stdout bytes; raise GitError on non-zero rc."""
    rc, out, err = run_sync(cwd, args, timeout)
    if rc != 0:
        raise GitError(args, rc, err.decode("utf-8", "replace"))
    return out


def _ui(fn):
    if sublime is None:
        fn()
    else:
        sublime.set_timeout(fn, 0)


def run_bg(fn, on_done=None, on_error=None):
    """Run fn() on a worker thread, deliver the result on the UI thread."""
    def worker():
        try:
            result = fn()
        except Exception as e:  # report anything to the UI, never crash the thread
            if on_error:
                _ui(lambda: on_error(e))
            return
        if on_done:
            _ui(lambda: on_done(result))

    threading.Thread(target=worker, daemon=True).start()
