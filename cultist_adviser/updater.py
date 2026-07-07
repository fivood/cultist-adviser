"""Self-update via GitHub Releases.

Flow: a background check compares the latest release tag against
__version__; the GUI shows a banner when newer. Clicking downloads the
release zip, stages the new exe next to the current one, then a batch
script swaps them after this process exits and relaunches.

Only the frozen exe self-updates; source runs just get the notice.
The check can be disabled with "update_check": false in settings.json.

GitHub is intermittently blocked in mainland China. We first try a
direct connection; on failure we walk a fallback list of URL-prefix
mirrors (settings.json "update_mirrors" wins, then the built-in list).
Mirrors accept the full GitHub URL appended to their base and reverse-
proxy it, which is the de-facto convention for public GH proxies.
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
from .config import PROJECT_DIR

RELEASES_API = "https://api.github.com/repos/fivood/cultist-adviser/releases/latest"
RELEASES_PAGE = "https://github.com/fivood/cultist-adviser/releases/latest"
SETTINGS_PATH = PROJECT_DIR / "settings.json"
# Reasonably stable public GH proxies as of 2026. Users can override with
# "update_mirrors" in settings.json (list or single string).
DEFAULT_MIRRORS = (
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
)
_UA = {"User-Agent": f"cultist-adviser/{__version__}"}


def _mirrors() -> list[str]:
    """Ordered mirror bases: user's settings first, then the built-ins.
    Each base is a URL prefix that, followed by a full github.com URL,
    reverse-proxies it — e.g. 'https://ghfast.top/https://github.com/…'."""
    try:
        s = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        s = {}
    custom = s.get("update_mirrors") or []
    if isinstance(custom, str):
        custom = [custom]
    seen: dict[str, None] = {}
    for m in list(custom) + list(DEFAULT_MIRRORS):
        m = str(m).strip()
        if m and not m.endswith("/"):
            m += "/"
        if m and m not in seen:
            seen[m] = None
    return list(seen)


def _fetch(url: str, timeout: float, use_mirrors: bool = True) -> bytes:
    """GET url, direct first; on failure fall back through the mirror list.
    Raises the last exception if every attempt fails."""
    errors: list[Exception] = []
    attempts = [url]
    if use_mirrors:
        attempts += [m + url for m in _mirrors()]
    for candidate in attempts:
        try:
            req = urllib.request.Request(candidate, headers=_UA)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            errors.append(e)
    raise errors[-1] if errors else RuntimeError("no attempts made")


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
        data = json.loads(_fetch(RELEASES_API, timeout).decode("utf-8"))
        tag = data.get("tag_name", "")
        if not is_newer(tag):
            return None
        asset = next((a for a in data.get("assets", [])
                      if a.get("name", "").endswith(".zip")), None)
        if not asset:
            return None
        return {"tag": tag, "url": asset["browser_download_url"],
                "size": int(asset.get("size") or 0),
                "notes": (data.get("body") or "")[:600]}
    except Exception:
        return None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def download_and_stage(url: str, timeout: float = 120.0,
                       expected_size: int = 0) -> Path:
    """Download the release zip and extract the new exe next to the current
    one as CultistAdviser.new.exe. Returns the staged path; raises on failure."""
    exe_dir = Path(sys.executable).parent if is_frozen() else Path.cwd()
    payload = _fetch(url, timeout)
    if expected_size and len(payload) != expected_size:
        raise RuntimeError(f"truncated download: {len(payload)}/{expected_size} bytes")
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


# The relaunch must NOT inherit PyInstaller's onefile bookkeeping variables:
# a child seeing _PYI_PARENT_PROCESS_LEVEL skips self-extraction and tries to
# load python from the OLD process's (already deleted) _MEI directory —
# "Failed to load Python DLL". Scrubbed both here and in the script.
_SWAP_BAT = r"""@echo off
cd /d "%~dp0"
set "_MEIPASS2="
set "_PYI_APPLICATION_HOME_DIR="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="
:wait
timeout /t 1 /nobreak >nul
del "CultistAdviser.exe" 2>nul
if exist "CultistAdviser.exe" goto wait
move /y "CultistAdviser.new.exe" "CultistAdviser.exe" >nul
start "" "CultistAdviser.exe"
del "%~f0"
"""


def _clean_env() -> dict:
    """os.environ minus PyInstaller's onefile parent/child markers."""
    return {k: v for k, v in os.environ.items()
            if k != "_MEIPASS2" and not k.startswith("_PYI_")}


def apply_and_exit():
    """Spawn the swap script and terminate. Frozen exe only."""
    exe_dir = Path(sys.executable).parent
    bat = exe_dir / "cultist_adviser_update.bat"
    bat.write_text(_SWAP_BAT, encoding="ascii")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) \
        | getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=str(exe_dir),
                     creationflags=flags, close_fds=True, env=_clean_env())
    os._exit(0)
