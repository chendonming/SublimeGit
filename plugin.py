"""SublimeGit — entry module.

Sublime Text imports every .py file in a package, so commands and event
listeners are discovered regardless of import order. The imports below make
the dependency order explicit and fail fast if something is broken.
"""

from SublimeGit.views import common  # noqa: F401
from SublimeGit.views import changes_panel, diff_view, file_history, timeline_panel  # noqa: F401
from SublimeGit import commands  # noqa: F401  (all command classes live here — see its docstring)
from SublimeGit import listeners  # noqa: F401
