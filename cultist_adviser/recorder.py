"""Run recorder: appends one compact snapshot per save-file change.

One JSONL file per character run, keyed by the save's DateTimeCreated — so a
run's history spans new-game to ending and survives GUI restarts. Written by
the advisor GUI; consumed by review.py.
"""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from .config import LOG_DIR
from .advisor import Advice

RUN_GLOB = "run_*.jsonl"
SESSION_GLOB = "session_*.jsonl"  # files from versions that recorded per GUI session


class SessionRecorder:
    def __init__(self):
        self.path: Path | None = None
        self._run_key: str | None = None
        self._last_recipes: dict | None = None

    def record(self, advice: Advice, state=None):
        created = getattr(state, "created_at", "") if state is not None else ""
        key = re.sub(r"\D", "", created)[:14]  # 2026-07-01T23:02:36… -> 20260701230236
        if self.path is None or key != self._run_key:
            self._run_key = key
            self._last_recipes = None
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if key:
                who = re.sub(r"\W", "", advice.character or "")[:16]
                self.path = LOG_DIR / f"run_{key}_{who or 'x'}.jsonl"
            else:  # no run identity in the save — fall back to a session file
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
        ending = getattr(state, "ending_id", "") if state is not None else ""
        if ending:
            snap["ending"] = ending
        # Cumulative recipe counts: only write when they changed, to keep lines lean.
        recipes = getattr(state, "recipe_executions", None) if state is not None else None
        if recipes and recipes != self._last_recipes:
            snap["recipes"] = recipes
            self._last_recipes = dict(recipes)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snap, ensure_ascii=False) + "\n")


def list_sessions() -> list[Path]:
    if not LOG_DIR.is_dir():
        return []
    paths = list(LOG_DIR.glob(RUN_GLOB)) + list(LOG_DIR.glob(SESSION_GLOB))
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


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
