"""Load local development environment files for the M5 CLI."""

from __future__ import annotations

import os
import re
from pathlib import Path


def load_project_env(project_root: Path) -> None:
    """Load local configuration without overriding process environment values.

    Loading ``.env.local`` first gives it precedence over ``.env``.  The
    default ``override=False`` also keeps variables supplied by the shell, CI,
    or a container above either file.
    """

    try:
        from dotenv import load_dotenv
    except ImportError:
        # Core PLC commands have no third-party Python dependencies. Their
        # simple KEY=VALUE configuration must work without the M5 extras.
        for path in (project_root / ".env.local", project_root / ".env"):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=\s*(.*)$", line)
                if not match:
                    continue
                key, value = match.groups()
                value = value.strip()
                if value.startswith(('"', "'")) and value.endswith(value[0]):
                    value = value[1:-1]
                else:
                    value = value.split(" #", 1)[0].rstrip()
                os.environ.setdefault(key, value)
    else:
        load_dotenv(project_root / ".env.local", override=False)
        load_dotenv(project_root / ".env", override=False)
