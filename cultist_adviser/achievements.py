"""Steam achievements: definitions from the game, unlocks from the save folder.

The game writes unlocks to `%LOCALLOW%/Weather Factory/Cultist Simulator/
achievements.json` as one base64-encoded `"key": "dd/mm/yyyy HH:MM:SS"` per
line. Cached parses live in memory for the process's life.
"""
import base64
import re
from functools import lru_cache
from pathlib import Path

from .config import SAVE_DIR
from .lexicon import CONTENT_DIR, _lenient_json

UNLOCK_PATH = SAVE_DIR / "achievements.json"

# Ending achievements whose id doesn't map to the ending id by stripping
# underscores — a few oddities from the DLC releases.
ENDING_ACH_TO_ENDING = {
    "colonel": "ascensioncolonel",
    "lionsmith": "ascensionlionsmith",
    "wolf": "ascensionwolf",
    "velvet": "victoryvelvet",
    "minorwintervictory": "minorpalestvictory",  # Ghoul renamed on release
}

# Endings the game defines but never awards an achievement for.
ENDINGS_WITHOUT_ACHIEVEMENT = frozenset({
    "longnightmareending", "rivalascension", "rivalascensionapostle",
    "turnasidevictory",
})


def _ach_ending_key(ach_id_lower: str) -> str:
    stripped = ach_id_lower.removeprefix("a_ending_")
    return ENDING_ACH_TO_ENDING.get(stripped, stripped.replace("_", ""))


@lru_cache(maxsize=1)
def definitions() -> dict[str, dict]:
    """All achievement definitions keyed by lower-case id."""
    defs: dict[str, dict] = {}
    folder = CONTENT_DIR / "core" / "achievements"
    if not folder.is_dir():
        return defs
    for path in folder.glob("*.json"):
        try:
            data = _lenient_json(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for value in data.values():
            if not isinstance(value, list):
                continue
            for a in value:
                if not isinstance(a, dict) or not a.get("id") or a.get("isCategory"):
                    continue
                defs[a["id"].lower()] = a
    return defs


_UNLOCK_LINE = re.compile(r'^"([^"]+)"\s*:\s*"([^"]+)"')


def parse_unlocks(path: Path | None = None) -> dict[str, str]:
    """achievement id (lower) -> unlock timestamp string. Empty when the file
    is missing (fresh install, Steam FIP mode) so downstream logic is safe."""
    path = path or UNLOCK_PATH
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {}
    unlocked: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            decoded = base64.b64decode(line + "===").decode("utf-8")
        except Exception:
            continue
        m = _UNLOCK_LINE.match(decoded)
        if m:
            unlocked[m.group(1).lower()] = m.group(2)
    return unlocked


def unlocked_endings(unlocks: dict[str, str] | None = None) -> set[str]:
    """Set of ending element ids the player has already achieved."""
    if unlocks is None:
        unlocks = parse_unlocks()
    out: set[str] = set()
    for aid in unlocks:
        if aid.startswith("a_ending_"):
            out.add(_ach_ending_key(aid))
    return out


def missing_by_kind(unlocks: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Unlocked-status inversion, grouped by the second segment of the id
    (ending / cult / mansus / promoted / summon)."""
    if unlocks is None:
        unlocks = parse_unlocks()
    unlocked = set(unlocks)
    groups: dict[str, list[str]] = {}
    for aid in definitions():
        if aid in unlocked:
            continue
        kind = aid.split("_")[1] if "_" in aid else "other"
        groups.setdefault(kind, []).append(aid)
    return groups


def progress() -> tuple[int, int]:
    unlocks = parse_unlocks()
    total = len(definitions())
    return len(set(unlocks) & set(definitions())), total


# ---- advisor helpers: which achievement is this run currently poised for? ----

# Non-ending achievements are all triggered by things the advisor already
# reasons about; map advisor's state predicates to achievement ids.

CULT_ASPECT_TO_ACH = {
    "edge": "a_cult_edge", "forge": "a_cult_forge", "grail": "a_cult_grail",
    "heart": "a_cult_heart", "knock": "a_cult_knock", "lantern": "a_cult_lantern",
    "moth": "a_cult_moth", "winter": "a_cult_winter",
    "secrethistories": "a_cult_secrethistories",
}

MANSUS_WAY_TO_ACH = {
    "waywood": "a_mansus_wood",
    "waywhite": "a_mansus_whitedoor",
    "waystag_after": "a_mansus_stagdoor",
    "wayspider": "a_mansus_spiderdoor",
    "waypeacock": "a_mansus_peacockdoor",
}

PROMOTED_ASPECT_TO_ACH = {
    "edge": "a_promoted_exalted_edge", "forge": "a_promoted_exalted_forge",
    "grail": "a_promoted_exalted_grail", "heart": "a_promoted_exalted_heart",
    "knock": "a_promoted_exalted_knock", "lantern": "a_promoted_exalted_lantern",
    "moth": "a_promoted_exalted_moth", "winter": "a_promoted_exalted_winter",
}


@lru_cache(maxsize=1)
def zh_labels() -> dict[str, dict]:
    """id -> {label, description} from the official zh-hans localization."""
    out: dict[str, dict] = {}
    folder = CONTENT_DIR / "loc_zh-hans" / "achievements"
    if not folder.is_dir():
        return out
    for path in folder.glob("*.json"):
        try:
            data = _lenient_json(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for value in data.values():
            if not isinstance(value, list):
                continue
            for a in value:
                if isinstance(a, dict) and a.get("id"):
                    out[a["id"].lower()] = {
                        "label": a.get("label", ""),
                        "desc": a.get("descriptionunlocked", "") or "",
                    }
    return out


def _norm_name(s: str) -> str:
    return re.sub(r"[\s　﻿]+", "", s)


@lru_cache(maxsize=2)
def guides(lang: str = "zh") -> dict[str, str]:
    """achievement id -> how-to text. The zh file is the hand-written source
    keyed by official zh names; the en file is its translation keyed by id."""
    fname = "achievement_guide.txt" if lang == "zh" else "achievement_guide_en.txt"
    path = Path(__file__).parent / fname
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    by_name: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") and stripped.endswith("--"):
            current = None
            continue
        if stripped.startswith("#"):
            current = by_name.setdefault(_norm_name(stripped[1:]), [])
            continue
        if current is not None and stripped:
            current.append(stripped)
    name_to_id = {_norm_name(v["label"]): k
                  for k, v in zh_labels().items() if v["label"]} \
        if lang == "zh" else {}
    out: dict[str, str] = {}
    for name, lines in by_name.items():
        # the en file is keyed by achievement id directly
        aid = name_to_id.get(name) if lang == "zh" else name
        if not aid or not lines:
            continue
        # zh entries open with flavor text (duplicates the official
        # description); the en file carries no flavor lines.
        body = (lines[1:] if len(lines) > 1 else lines) if lang == "zh" else lines
        out[aid] = "\n".join(body)
    return out
