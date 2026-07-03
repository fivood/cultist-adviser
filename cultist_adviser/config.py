"""Paths and settings for the adviser.

Autodetects common install locations. Override with environment variables
when detection misses:
  CULTIST_GAME_DIR  — the game's install folder (contains cultistsimulator_Data)
  CULTIST_SAVE_DIR  — the folder containing save.json
"""
import os
from pathlib import Path

_GAME_CANDIDATES = [
    Path(f"{d}:/SteamLibrary/steamapps/common/Cultist Simulator") for d in "CDEFG"
] + [
    Path("C:/Program Files (x86)/Steam/steamapps/common/Cultist Simulator"),
    Path("C:/Program Files/Steam/steamapps/common/Cultist Simulator"),
]


def _detect_game_dir() -> Path:
    env = os.environ.get("CULTIST_GAME_DIR")
    if env:
        return Path(env)
    for p in _GAME_CANDIDATES:
        if (p / "cultistsimulator_Data").is_dir():
            return p
    return _GAME_CANDIDATES[0]  # names still resolve to raw ids if this is wrong


GAME_DIR = _detect_game_dir()
SAVE_DIR = Path(os.environ.get("CULTIST_SAVE_DIR")
                or Path.home() / "AppData/LocalLow/Weather Factory/Cultist Simulator")
SAVE_PATH = SAVE_DIR / "save.json"

PROJECT_DIR = Path(__file__).parent
LOG_DIR = PROJECT_DIR / "logs"

SAVE_POLL_INTERVAL = 0.5  # seconds between save.json mtime checks
