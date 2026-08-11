"""macOS notification via osascript; never raises."""

from __future__ import annotations

import subprocess

OSASCRIPT = "/usr/bin/osascript"


def notify(title: str, message: str) -> bool:
    safe = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'display notification "{safe(message[:200])}" '
        f'with title "{safe(title[:80])}"'
    )
    try:
        result = subprocess.run(
            [OSASCRIPT, "-e", script], capture_output=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False
