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
SECTIONS = ("elements", "verbs", "legacies")

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


def _load():
    global _lexicon, _recipes
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _lexicon = cache["entities"]
            _recipes = cache["recipes"]
            return
        except Exception:
            pass
    lex: dict[str, dict[str, str]] = {}
    rec: dict[str, dict[str, str]] = {}
    for root, key in ((CONTENT_DIR / "core", "en"), (CONTENT_DIR / "loc_zh-hans", "zh")):
        _harvest(root, key, SECTIONS, lex)
        _harvest(root, key, ("recipes",), rec)
    _lexicon, _recipes = lex, rec
    if lex:
        try:
            CACHE_PATH.write_text(json.dumps({"entities": lex, "recipes": rec},
                                             ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


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
