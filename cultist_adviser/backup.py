"""Rolling save backups, written to the adviser's own folder.

Two kinds: routine copies (at most one per ROUTINE_MIN_GAP, newest
ROUTINE_KEEP kept) and danger snapshots taken the moment a lethal verb
appears (suffix _danger, newest DANGER_KEEP kept). The game's own save is
never touched — restoring is a manual copy with the game closed.
Disable with "backup": false in settings.json.
"""
import time
from datetime import datetime
from pathlib import Path

from .config import PROJECT_DIR

BACKUP_DIR = PROJECT_DIR / "save_backups"
ROUTINE_KEEP = 30
DANGER_KEEP = 10
ROUTINE_MIN_GAP = 120.0  # seconds


class SaveBackupper:
    def __init__(self):
        self.last_routine = 0.0
        self._alert_verbs_seen: set[str] = set()

    def backup(self, data: bytes, advice, alert_verbs: set) -> None:
        """Called on every accepted save change; never raises."""
        try:
            now = time.time()
            present = {v.verb_id for v in advice.verbs
                       if v.verb_id in alert_verbs}
            fresh_danger = bool(present - self._alert_verbs_seen)
            self._alert_verbs_seen = present
            if not fresh_danger and now - self.last_routine < ROUTINE_MIN_GAP:
                return
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = "_danger" if fresh_danger else ""
            (BACKUP_DIR / f"save_{stamp}{suffix}.json").write_bytes(data)
            if not fresh_danger:
                self.last_routine = now
            self._prune()
        except Exception:
            pass  # backups must never break the adviser

    def _prune(self):
        for pattern, keep in (("save_*_danger.json", DANGER_KEEP),):
            files = sorted(BACKUP_DIR.glob(pattern))
            for p in files[:-keep] if len(files) > keep else []:
                p.unlink(missing_ok=True)
        routine = sorted(p for p in BACKUP_DIR.glob("save_*.json")
                         if not p.name.endswith("_danger.json"))
        for p in routine[:-ROUTINE_KEEP] if len(routine) > ROUTINE_KEEP else []:
            p.unlink(missing_ok=True)
