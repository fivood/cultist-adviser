"""Recipe knowledge: how to obtain cards, built from the game's own recipe JSON.

Indexes every main-verb recipe whose effects produce an element, plus each
element's aspects (the save file stores only entity ids, so aspect checks such
as "is this card an acquaintance?" need the game's element definitions).
Cached to knowledge_cache.json — delete it to rebuild after a game update.
"""
import json
import re

from .config import PROJECT_DIR
from .lexicon import CONTENT_DIR, _lenient_json, display_name, recipe_name, tr

CACHE_PATH = PROJECT_DIR / "knowledge_cache.json"
MAIN_VERBS = {"work", "study", "dream", "explore", "talk", "time"}
LORE_ASPECT_NAMES = ("edge", "forge", "grail", "heart", "knock",
                     "lantern", "moth", "winter")

_recipes: list[dict] = []          # {id, action, craftable, req{}, eff{}}
_obtain: dict[str, list[int]] = {}  # element id -> indices into _recipes
_el_aspects: dict[str, dict] = {}   # element id -> {aspect: value}
_vaults: dict[str, list[str]] = {}  # expedition site -> obstacle element ids
_counters: dict[str, list[str]] = {}  # obstacle -> lore aspects that beat it


def _parse_element_aspects() -> dict[str, dict]:
    aspects: dict[str, dict] = {}
    folder = CONTENT_DIR / "core" / "elements"
    if not folder.is_dir():
        return aspects
    for path in folder.glob("*.json"):
        try:
            data = _lenient_json(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for value in data.values():
            if not isinstance(value, list):
                continue
            for e in value:
                if not isinstance(e, dict) or not e.get("id") or e.get("isAspect"):
                    continue
                asp = {}
                for k, v in (e.get("aspects") or {}).items():
                    try:
                        asp[str(k).lower()] = int(v)
                    except (TypeError, ValueError):
                        continue
                aspects[str(e["id"]).lower()] = asp
    return aspects


def _parse_expeditions() -> tuple[dict, dict]:
    """Vault -> obstacles (from *_setup recipe effects) and obstacle -> counter
    aspects (from explorevault<obstacle>_<tier><aspect> resolution recipe ids)."""
    vaults: dict[str, list[str]] = {}
    counters: dict[str, list[str]] = {}
    folder = CONTENT_DIR / "core" / "recipes"
    if not folder.is_dir():
        return vaults, counters
    tier_re = re.compile(
        r"^explorevault(.+)_(?:high|mid|low)(%s)$" % "|".join(LORE_ASPECT_NAMES))
    for path in folder.glob("explore_vault*.json"):
        try:
            data = _lenient_json(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for value in data.values():
            if not isinstance(value, list):
                continue
            for r in value:
                if not isinstance(r, dict) or not r.get("id"):
                    continue
                rid = str(r["id"]).lower()
                if rid.endswith("_setup"):
                    site = next((str(k).lower() for k in (r.get("requirements") or {})
                                 if str(k).lower().startswith("vault")), None)
                    if site:
                        vaults[site] = [str(k).lower()
                                        for k in (r.get("effects") or {})]
                m = tier_re.match(rid)
                if m:
                    obstacle, aspect = m.group(1), m.group(2)
                    if aspect not in counters.setdefault(obstacle, []):
                        counters[obstacle].append(aspect)
    return vaults, counters


def _load():
    global _recipes, _obtain, _el_aspects, _vaults, _counters
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _recipes, _obtain = cache["recipes"], cache["obtain"]
            _el_aspects = cache["aspects"]
            _vaults, _counters = cache["vaults"], cache["counters"]
            return  # KeyError on caches from older versions -> rebuild below
        except Exception:
            pass
    recipes: list[dict] = []
    folder = CONTENT_DIR / "core" / "recipes"
    if folder.is_dir():
        for path in folder.glob("*.json"):
            if "debug" in path.name.lower():
                continue
            try:
                data = _lenient_json(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
            for value in data.values():
                if not isinstance(value, list):
                    continue
                for r in value:
                    if not isinstance(r, dict) or not r.get("id"):
                        continue
                    action = str(r.get("actionid") or r.get("actionId") or "").lower()
                    if action not in MAIN_VERBS:
                        continue
                    req, eff = {}, {}
                    for k, v in (r.get("requirements") or {}).items():
                        try:
                            n = int(v)
                        except (TypeError, ValueError):
                            continue
                        if n > 0:
                            req[str(k).lower()] = n
                    for k, v in (r.get("effects") or {}).items():
                        try:
                            n = int(v)
                        except (TypeError, ValueError):
                            continue
                        if n > 0:
                            eff[str(k).lower()] = n
                    if eff:
                        recipes.append({"id": str(r["id"]).lower(), "action": action,
                                        "craftable": bool(r.get("craftable", False)),
                                        "req": req, "eff": eff})
    obtain: dict[str, list[int]] = {}
    for i, r in enumerate(recipes):
        for eid in r["eff"]:
            obtain.setdefault(eid, []).append(i)
    _recipes, _obtain = recipes, obtain
    _el_aspects = _parse_element_aspects()
    _vaults, _counters = _parse_expeditions()
    if recipes:
        try:
            CACHE_PATH.write_text(json.dumps({"recipes": recipes, "obtain": obtain,
                                              "aspects": _el_aspects,
                                              "vaults": _vaults,
                                              "counters": _counters},
                                             ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def _way_text(r: dict) -> str:
    parts = []
    for k, n in r["req"].items():
        name = display_name(k)
        parts.append(f"{name}×{n}" if n > 1 else name)
    inputs = " + ".join(parts) if parts else tr("（无需材料）", "(no ingredients)")
    text = f"「{display_name(r['action'])}」 {inputs}  →  {recipe_name(r['id'])}"
    if not r["craftable"]:
        text += tr("（连锁触发，不能直接开始）", " (follow-up, not directly startable)")
    return text


def _ranked_ways(entity_id: str, available: set | None) -> list[dict]:
    """Craftable first; among those, ways whose ingredients we hold, then fewest inputs."""
    avail = {a.lower() for a in available} if available else set()

    def key(r):
        missing = sum(1 for k in r["req"] if k not in avail) if avail else 0
        return (not r["craftable"], missing, len(r["req"]))

    ways, seen = [], set()
    for i in _obtain.get(entity_id.lower(), []):
        r = _recipes[i]
        sig = (r["action"], tuple(sorted(r["req"].items())))
        if sig in seen:
            continue
        seen.add(sig)
        ways.append(r)
    return sorted(ways, key=key)


def obtain_ways(entity_id: str, limit: int = 6, available: set | None = None) -> list[str]:
    return [_way_text(r) for r in _ranked_ways(entity_id, available)[:limit]]


def element_aspects(entity_id: str) -> dict:
    """Aspects of an element as defined by the game (empty dict if unknown)."""
    return _el_aspects.get(entity_id.lower(), {})


def has_aspect(entity_id: str, aspect: str) -> bool:
    # An element's own id counts as an aspect of itself (engine semantics).
    if entity_id.lower() == aspect.lower():
        return True
    return bool(element_aspects(entity_id).get(aspect))


def vault_obstacles(entity_id: str) -> list[str]:
    """Obstacle element ids a base-game expedition site will spawn."""
    return _vaults.get(entity_id.lower(), [])


def obstacle_counters(obstacle_id: str) -> list[str]:
    """Lore aspects that can beat an expedition obstacle (tiers 1/5/10)."""
    return _counters.get(obstacle_id.lower(), [])


def obtain_hint(entity_id: str, available: set | None = None) -> str:
    """Best craftable way, as a one-line hint for suggestions."""
    craftable = [r for r in _ranked_ways(entity_id, available) if r["craftable"]]
    if not craftable:
        return ""
    r = craftable[0]
    parts = [display_name(k) for k in r["req"]]
    inputs = " + ".join(parts) if parts else tr("直接开始", "start directly")
    return tr(f"获得方式：「{display_name(r['action'])}」+ {inputs}。",
              f"Obtain via {display_name(r['action'])} + {inputs}.")


_load()
