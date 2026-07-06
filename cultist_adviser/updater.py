"""Self-update via GitHub Releases.

Flow: a background check compares the latest release tag against
__version__; the GUI shows a banner when newer. Clicking downloads the
release zip, stages the new exe next to the current one, then a batch
script swaps them after this process exits and relaunches.

Only the frozen exe self-updates; source runs just get the notice.
The check can be disabled with "update_check": false in settings.json.
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from . import __version__

RELEASES_API = "https://api.github.com/repos/fivood/cultist-adviser/releases/latest"
RELEASES_PAGE = "https://github.com/fivood/cultist-adviser/releases/latest"
_UA = {"User-Agent": f"cultist-adviser/{__version__}"}


def _ver_tuple(tag: str) -> tuple:
    return tuple(int(p) for p in tag.lstrip("vV").split(".") if p.isdigit())


def is_newer(tag: str, current: str = __version__) -> bool:
    try:
        return _ver_tuple(tag) > _ver_tuple(current)
    except ValueError:
        return False


def check_latest(timeout: float = 6.0) -> dict | None:
    """{tag, url, notes} of the latest release, or None (offline/error/current).
    Never raises — callers run this on a background thread at startup."""
    try:
        req = urllib.request.Request(RELEASES_API, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name", "")
        if not is_newer(tag):
            return None
        asset = next((a for a in data.get("assets", [])
                      if a.get("name", "").endswith(".zip")), None)
        if not asset:
            return None
        return {"tag": tag, "url": asset["browser_download_url"],
                "notes": (data.get("body") or "")[:600]}
    except Exception:
        return None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def download_and_stage(url: str, timeout: float = 120.0) -> Path:
    """Download the release zip and extract the new exe next to the current
    one as CultistAdviser.new.exe. Returns the staged path; raises on failure."""
    exe_dir = Path(sys.executable).parent if is_frozen() else Path.cwd()
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    tmp = Path(tempfile.gettempdir()) / "cultist_adviser_update.zip"
    tmp.write_bytes(payload)
    staged = exe_dir / "CultistAdviser.new.exe"
    with zipfile.ZipFile(tmp) as z:
        with z.open("CultistAdviser.exe") as src:
            staged.write_bytes(src.read())
    tmp.unlink(missing_ok=True)
    if staged.stat().st_size < 1_000_000:
        staged.unlink(missing_ok=True)
        raise RuntimeError("downloaded exe is implausibly small")
    return staged


_SWAP_BAT = r"""@echo off
cd /d "%~dp0"
:wait
timeout /t 1 /nobreak >nul
del "CultistAdviser.exe" 2>nul
if exist "CultistAdviser.exe" goto wait
move /y "CultistAdviser.new.exe" "CultistAdviser.exe" >nul
start "" "CultistAdviser.exe"
del "%~f0"
"""


def apply_and_exit():
    """Spawn the swap script and terminate. Frozen exe only."""
    exe_dir = Path(sys.executable).parent
    bat = exe_dir / "cultist_adviser_update.bat"
    bat.write_text(_SWAP_BAT, encoding="ascii")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) \
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe_dir),
                     creationflags=flags, close_fds=True)
    os._exit(0)
