"""Session recorder: appends one compact snapshot per save-file change.

Written by the advisor GUI; consumed by review.py. One JSONL file per session
under logs/, named session_YYYYmmdd_HHMMSS.jsonl.
"""
import json
import time
from datetime import datetime
from pathlib import Path

from .config import LOG_DIR
from .advisor import Advice

SESSION_GLOB = "session_*.jsonl"


class SessionRecorder:
    def __init__(self):
        self.path: Path | None = None  # created lazily on first snapshot

    def record(self, advice: Advice):
        if self.path is None:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path = LOG_DIR / f"session_{stamp}.jsonl"
        snap = {
            "t": round(time.time(), 1),
            "character": advice.character,
            "legacy": advice.legacy,
            "resources": {r.entity_id: r.quantity for r in advice.resources},
            "verbs": [[v.verb_id, v.recipe_id, round(v.time_remaining, 1)]
                      for v in advice.verbs],
            "urgent": [s.title for s in advice.suggestions if s.urgent],
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")


def list_sessions() -> list[Path]:
    if not LOG_DIR.is_dir():
        return []
    return sorted(LOG_DIR.glob(SESSION_GLOB), reverse=True)


def load_session(path: Path) -> list[dict]:
    snaps = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    snaps.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return snaps
