"""id -> localized label dictionary, harvested from the game's own content JSON.

English labels come from StreamingAssets/content/core, Chinese from
content/loc_zh-hans. Cached to lexicon_cache.json — delete that file to
rebuild after a game update.
"""
import json
from pathlib import Path

from .config import GAME_DIR, PROJECT_DIR

CONTENT_DIR = GAME_DIR / "cultistsimulator_Data" / "StreamingAssets" / "content"
CACHE_PATH = PROJECT_DIR / "lexicon_cache.json"
SECTIONS = ("elements", "verbs", "legacies", "endings")

_lexicon: dict[str, dict[str, str]] = {}
_recipes: dict[str, dict[str, str]] = {}
_lang = "zh"


def set_language(lang: str):
    global _lang
    _lang = lang if lang in ("zh", "en") else "zh"


def get_language() -> str:
    return _lang


def tr(zh: str, en: str) -> str:
    return zh if _lang == "zh" else en


def _lenient_json(text: str):
    """Game content JSON allows trailing commas and raw control chars in strings."""
    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        pass
    out = []
    in_str = False
    escaped = False
    for ch in text:
        if in_str:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            continue
        if ch in "}]":
            # drop a trailing comma before a closer
            i = len(out) - 1
            while i >= 0 and out[i] in " \t\r\n":
                i -= 1
            if i >= 0 and out[i] == ",":
                del out[i]
        out.append(ch)
    return json.loads("".join(out), strict=False)


def _harvest(root: Path, lang_key: str, sections: tuple, out: dict):
    for section in sections:
        folder = root / section
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                data = _lenient_json(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue  # give up on files even lenient parsing can't handle
            for value in data.values():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if isinstance(item, dict) and item.get("id") and item.get("label"):
                        out.setdefault(str(item["id"]).lower(), {})[lang_key] = str(item["label"])


# Minimum entities we expect from a healthy build — used to detect cache/game
# folders that harvested to an empty or partial state (typically because the
# user's game path wasn't auto-detected). About 2200 entities are normal on
# base game + all DLC; anything under a few hundred means fallback is needed.
_HEALTHY_MIN = 500

BUNDLED_CACHE = Path(__file__).parent / "lexicon_cache_bundled.json"


def _load_from_cache(path: Path) -> tuple[dict, dict] | None:
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
        if cache.get("sections") != list(SECTIONS):
            return None
        return cache["entities"], cache["recipes"]
    except Exception:
        return None


def _load():
    global _lexicon, _recipes
    # 1. User-local cache (built from their game folder)
    cached = _load_from_cache(CACHE_PATH) if CACHE_PATH.exists() else None
    if cached and len(cached[0]) >= _HEALTHY_MIN:
        _lexicon, _recipes = cached
        return
    # 2. Try harvesting live from the detected game folder
    lex: dict[str, dict[str, str]] = {}
    rec: dict[str, dict[str, str]] = {}
    for root, key in ((CONTENT_DIR / "core", "en"), (CONTENT_DIR / "loc_zh-hans", "zh")):
        _harvest(root, key, SECTIONS, lex)
        _harvest(root, key, ("recipes",), rec)
    if len(lex) >= _HEALTHY_MIN:
        _lexicon, _recipes = lex, rec
        try:
            CACHE_PATH.write_text(json.dumps({"sections": list(SECTIONS),
                                              "entities": lex, "recipes": rec},
                                             ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return
    # 3. Fallback: the release-time bundled cache (may lag one game version but
    # spares users with an unusual install location from raw-id chinese).
    bundled = _load_from_cache(BUNDLED_CACHE) if BUNDLED_CACHE.exists() else None
    if bundled:
        _lexicon, _recipes = bundled
        return
    # 4. Nothing worked — leave whatever we harvested; display_name falls
    # through to the raw id and the GUI can surface the diagnostic.
    _lexicon, _recipes = lex, rec


def _lookup(table: dict, key: str) -> str:
    entry = table.get(key.lower())
    if not entry:
        return key
    return entry.get(_lang) or entry.get("en") or key


def display_name(entity_id: str) -> str:
    return _lookup(_lexicon, entity_id)


def recipe_name(recipe_id: str) -> str:
    return _lookup(_recipes, recipe_id)


def situation_name(verb_id: str, recipe_id: str = "") -> str:
    """Season verbs (despair, visions…) get their label from the running recipe."""
    if recipe_id and recipe_id.lower() in _recipes:
        return _lookup(_recipes, recipe_id)
    return _lookup(_lexicon, verb_id)


def size() -> int:
    return len(_lexicon)


_load()
