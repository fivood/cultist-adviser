"""Recipe knowledge: how to obtain cards, built from the game's own recipe JSON.

Indexes every main-verb recipe whose effects produce an element, plus each
element's aspects (the save file stores only entity ids, so aspect checks such
as "is this card an acquaintance?" need the game's element definitions).
Cached to knowledge_cache.json — delete it to rebuild after a game update.
"""
import json
import re
from pathlib import Path

from .config import PROJECT_DIR
from .lexicon import CONTENT_DIR, _lenient_json, display_name, recipe_name, tr

CACHE_PATH = PROJECT_DIR / "knowledge_cache.json"
BUNDLED_CACHE = Path(__file__).parent / "knowledge_cache_bundled.json"
_HEALTHY_MIN = 300  # a live index of 1300+ recipes is normal
# The verbs every base-game run has; routes through other verbs are
# profession-specific and get demoted unless the player's save has them.
BASE_VERBS = {"work", "study", "dream", "explore", "talk", "time"}
LORE_ASPECT_NAMES = ("edge", "forge", "grail", "heart", "knock",
                     "lantern", "moth", "winter")

_recipes: list[dict] = []          # {id, action, craftable, req{}, eff{}}
_obtain: dict[str, list[int]] = {}  # element id -> indices into _recipes
_uses: dict[str, list[int]] = {}    # element id -> recipes that take it as input
_el_aspects: dict[str, dict] = {}   # element id -> {aspect: value}
_decays: dict[str, str] = {}        # element id -> what it decays into
_lifetimes: dict[str, int] = {}     # element id -> natural lifetime in seconds
_verb_slots: dict[str, list] = {}   # verb id -> ordered primary slot specs
_el_slots: dict[str, list] = {}     # element id -> slots it opens, per action
_vaults: dict[str, list[str]] = {}  # expedition site -> obstacle element ids
_counters: dict[str, list[str]] = {}  # obstacle -> lore aspects that beat it


def _norm_slot(s: dict) -> dict:
    req, forb = {}, {}
    for k, v in (s.get("required") or {}).items():
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n > 0:
            req[str(k).lower()] = n
    for k in (s.get("forbidden") or {}):
        forb[str(k).lower()] = 1
    return {"req": req, "forb": forb}


def _parse_verb_slots() -> dict:
    slots: dict[str, list] = {}
    folder = CONTENT_DIR / "core" / "verbs"
    if not folder.is_dir():
        return slots
    for path in folder.glob("*.json"):
        try:
            data = _lenient_json(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        for value in data.values():
            if not isinstance(value, list):
                continue
            for v in value:
                if not isinstance(v, dict) or not v.get("id"):
                    continue
                specs = []
                if isinstance(v.get("slot"), dict):
                    specs.append(_norm_slot(v["slot"]))
                for s in v.get("slots") or []:
                    if isinstance(s, dict):
                        specs.append(_norm_slot(s))
                if specs:
                    slots[str(v["id"]).lower()] = specs
    return slots


def _parse_elements() -> tuple[dict, dict, dict, dict]:
    aspects: dict[str, dict] = {}
    decays: dict[str, str] = {}
    lifetimes: dict[str, int] = {}
    _element_slots_out: dict[str, list] = {}
    folder = CONTENT_DIR / "core" / "elements"
    if not folder.is_dir():
        return aspects, decays, lifetimes, _element_slots_out
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
                eid = str(e["id"]).lower()
                asp = {}
                for k, v in (e.get("aspects") or {}).items():
                    try:
                        asp[str(k).lower()] = int(v)
                    except (TypeError, ValueError):
                        continue
                aspects[eid] = asp
                el_slots = []
                for s in e.get("slots") or []:
                    if isinstance(s, dict):
                        spec = _norm_slot(s)
                        spec["action"] = str(s.get("actionId")
                                             or s.get("actionid") or "").lower()
                        el_slots.append(spec)
                if el_slots:
                    _element_slots_out[eid] = el_slots
                if e.get("decayTo"):
                    decays[eid] = str(e["decayTo"]).lower()
                try:
                    life = int(e.get("lifetime", 0))
                except (TypeError, ValueError):
                    life = 0
                if life > 0:
                    lifetimes[eid] = life
    return aspects, decays, lifetimes, _element_slots_out


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
    for path in list(folder.glob("explore_vault*.json")) + \
            list(folder.glob("explore_obstacles_*.json")):
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
    global _recipes, _obtain, _uses, _el_aspects, _vaults, _counters
    global _decays, _lifetimes, _verb_slots, _el_slots
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if cache.get("v") != 5:
                raise KeyError("stale cache format")
            _recipes, _obtain = cache["recipes"], cache["obtain"]
            _el_aspects = cache["aspects"]
            _decays, _lifetimes = cache["decays"], cache["lifetimes"]
            _verb_slots, _el_slots = cache["verb_slots"], cache["el_slots"]
            _vaults, _counters = cache["vaults"], cache["counters"]
            _uses = cache["uses"]
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
                    if not action:
                        continue
                    # Every verb is indexed — profession-specific systems
                    # (Exile's use/send, the Ghoul's seances, club events)
                    # have their own obtain/use routes. Ranking demotes
                    # routes through verbs the player doesn't have.
                    req, neg, eff = {}, {}, {}
                    for k, v in (r.get("requirements") or {}).items():
                        try:
                            n = int(v)
                        except (TypeError, ValueError):
                            continue
                        if n > 0:
                            req[str(k).lower()] = n
                        elif n < 0:
                            neg[str(k).lower()] = n
                    for k, v in (r.get("effects") or {}).items():
                        try:
                            n = int(v)
                        except (TypeError, ValueError):
                            # String values reference an aspect quantity
                            # ("contentment": "comfort" = one per comfort) —
                            # the recipe does produce the element.
                            n = 1 if isinstance(v, str) and v.strip() else 0
                        if n > 0:
                            eff[str(k).lower()] = n
                    # Effect-less recipes still matter for the startable
                    # scanner (their payoff arrives via linked recipes).
                    if eff or (r.get("craftable") and req):
                        recipes.append({"id": str(r["id"]).lower(), "action": action,
                                        "craftable": bool(r.get("craftable", False)),
                                        "hint": bool(r.get("hintonly", False)),
                                        "req": req, "neg": neg, "eff": eff})
    obtain: dict[str, list[int]] = {}
    uses: dict[str, list[int]] = {}
    for i, r in enumerate(recipes):
        for eid in r["eff"]:
            obtain.setdefault(eid, []).append(i)
        for eid in r["req"]:
            uses.setdefault(eid, []).append(i)
    if len(recipes) >= _HEALTHY_MIN:
        _recipes, _obtain, _uses = recipes, obtain, uses
        _el_aspects, _decays, _lifetimes, _el_slots = _parse_elements()
        _verb_slots = _parse_verb_slots()
        _vaults, _counters = _parse_expeditions()
        try:
            CACHE_PATH.write_text(json.dumps({"v": 5,
                                              "recipes": recipes, "obtain": obtain,
                                              "uses": uses,
                                              "aspects": _el_aspects,
                                              "decays": _decays,
                                              "lifetimes": _lifetimes,
                                              "verb_slots": _verb_slots,
                                              "el_slots": _el_slots,
                                              "vaults": _vaults,
                                              "counters": _counters},
                                             ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return
    # Fallback: bundled cache from build time.
    if BUNDLED_CACHE.exists():
        try:
            cache = json.loads(BUNDLED_CACHE.read_text(encoding="utf-8"))
            if cache.get("v") == 5:
                _recipes, _obtain = cache["recipes"], cache["obtain"]
                _el_aspects = cache["aspects"]
                _decays, _lifetimes = cache["decays"], cache["lifetimes"]
                _verb_slots, _el_slots = cache["verb_slots"], cache["el_slots"]
                _vaults, _counters = cache["vaults"], cache["counters"]
                _uses = cache["uses"]
                return
        except Exception:
            pass
    # Nothing to fall back on — leave the empty partial as-is.
    _recipes, _obtain, _uses = recipes, obtain, uses


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


def _verb_gap(action: str, verbs: set | None) -> int:
    """1 when the route runs through a verb this player doesn't have (e.g. the
    Exile's use/send shown to an Aspirant, or vice versa)."""
    if verbs is None:
        return 0 if action in BASE_VERBS else 1
    return 0 if action in verbs else 1


def _ranked_ways(entity_id: str, available: set | None,
                 verbs: set | None = None) -> list[dict]:
    """Craftable first, this profession's verbs first, then ways whose
    ingredients we hold, then fewest inputs."""
    avail = {a.lower() for a in available} if available else set()

    def key(r):
        missing = sum(1 for k in r["req"] if k not in avail) if avail else 0
        return (not r["craftable"], _verb_gap(r["action"], verbs),
                missing, len(r["req"]))

    ways, seen = [], set()
    for i in _obtain.get(entity_id.lower(), []):
        r = _recipes[i]
        sig = (r["action"], tuple(sorted(r["req"].items())))
        if sig in seen:
            continue
        seen.add(sig)
        ways.append(r)
    return sorted(ways, key=key)


def obtain_ways(entity_id: str, limit: int = 6, available: set | None = None,
                verbs: set | None = None) -> list[str]:
    return [_way_text(r) for r in _ranked_ways(entity_id, available, verbs)[:limit]]


def _use_text(r: dict, hero: str) -> str:
    """Format a recipe as 'verb + other-inputs → result', with the pivot card
    downplayed since we're viewing from its perspective."""
    other = [f"{display_name(k)}×{n}" if n > 1 else display_name(k)
             for k, n in r["req"].items() if k != hero]
    inputs = " + ".join(other) if other else tr("直接投入", "on its own")
    text = f"「{display_name(r['action'])}」 {inputs}  →  {recipe_name(r['id'])}"
    if not r["craftable"]:
        text += tr("（连锁触发）", " (follow-up)")
    return text


def use_ways(entity_id: str, limit: int = 8, available: set | None = None,
             verbs: set | None = None) -> list[str]:
    """Recipes that consume this card as input. Craftable first, this
    profession's verbs first, then whichever the player can pay for right
    now, then fewest extra inputs. When nothing matches the id directly
    (typical for follower/acquaintance/prisoner cards), fall back to the
    card's own aspects — a card is a legitimate stand-in for any aspect
    it carries."""
    eid = entity_id.lower()
    avail = {a.lower() for a in available} if available else set()

    def key(r):
        missing = sum(1 for k in r["req"]
                      if k != eid and k not in avail) if avail else 0
        return (not r["craftable"], _verb_gap(r["action"], verbs),
                missing, len(r["req"]))

    ways, seen = [], set()
    indices = list(_uses.get(eid, []))
    if not indices:
        for aspect in _el_aspects.get(eid, {}):
            indices.extend(_uses.get(aspect, []))
    for i in indices:
        r = _recipes[i]
        sig = (r["action"], tuple(sorted(r["req"].items())),
               tuple(sorted(r["eff"].items())))
        if sig in seen:
            continue
        seen.add(sig)
        ways.append(r)
    pivot = eid if _uses.get(eid) else next(iter(_el_aspects.get(eid, {})), eid)
    return [_use_text(r, pivot) for r in sorted(ways, key=key)[:limit]]


def _unit_aspects(entity_id: str) -> dict:
    """Aspects one copy of a card contributes: its own id at 1 plus its aspects."""
    eid = entity_id.lower()
    asp = {eid: 1}
    for k, v in _el_aspects.get(eid, {}).items():
        asp[k] = asp.get(k, 0) + v
    return asp


def _match_requirements(req: dict, neg: dict, cards: dict) -> dict | None:
    """Greedy pick of cards (eid -> copies) whose combined aspects satisfy the
    positive requirements without tripping the negative ones. Approximates the
    engine (which checks the cards actually slotted): we cap the pick at 4
    distinct cards / 8 copies, since more can rarely co-slot in one verb."""
    if not req:
        return None
    need = dict(req)
    chosen: dict[str, int] = {}
    for _ in range(8):
        if not need:
            break
        best_eid, best_gain = None, 0
        for eid, qty in cards.items():
            if chosen.get(eid, 0) >= qty:
                continue
            asp = _unit_aspects(eid)
            gain = sum(min(asp.get(k, 0), v) for k, v in need.items())
            if gain > best_gain:
                best_gain, best_eid = gain, eid
        if best_eid is None:
            return None
        chosen[best_eid] = chosen.get(best_eid, 0) + 1
        asp = _unit_aspects(best_eid)
        for k in list(need):
            need[k] -= asp.get(k, 0)
            if need[k] <= 0:
                del need[k]
    if need or len(chosen) > 4:
        return None
    agg: dict[str, int] = {}
    for eid, n in chosen.items():
        for k, v in _unit_aspects(eid).items():
            agg[k] = agg.get(k, 0) + v * n
    for k, v in neg.items():  # engine: value -n means "aspect must be < n"
        if agg.get(k, 0) >= -v:
            return None
    return chosen


def _fits_slot(entity_id: str, spec: dict) -> bool:
    """Engine semantics (SphereSpec.CheckPayloadAllowedHere): per-unit aspects,
    any forbidden aspect present blocks, empty required passes, otherwise ANY
    single required aspect at its value qualifies."""
    unit = _unit_aspects(entity_id)
    if any(unit.get(k, 0) > 0 for k in spec["forb"]):
        return False
    req = spec["req"]
    if not req:
        return True
    return any(unit.get(k, 0) >= v for k, v in req.items())


def _slots_opened_by(entity_id: str, action: str) -> list[dict]:
    return [s for s in _el_slots.get(entity_id.lower(), [])
            if s.get("action") in (action, "")]


def _useful_units(entity_id: str, avail: int, need: dict) -> int:
    """Same-name cards merge into one stack in a slot, multiplying aspects —
    how many copies are worth stacking against the remaining need."""
    unit = _unit_aspects(entity_id)
    want = 1
    for k, v in need.items():
        u = unit.get(k, 0)
        if u > 0:
            want = max(want, -(-v // u))
    return min(avail, want)


def _slot_sim(req: dict, neg: dict, action: str, cards: dict) -> dict | None:
    """Simulate actually slotting cards: a pivot goes into the verb's primary
    slot, recursively opening the slots its element defines for this verb;
    each slot takes one stack. Returns placed cards or None."""
    primaries = _verb_slots.get(action) or [{"req": {}, "forb": {}}]

    def apply(placed, agg, need, eid, units):
        placed[eid] = placed.get(eid, 0) + units
        unit = _unit_aspects(eid)
        for k, v in unit.items():
            agg[k] = agg.get(k, 0) + v * units
        for k in list(need):  # need holds REMAINING amounts
            rest = req[k] - agg.get(k, 0)
            if rest <= 0:
                del need[k]
            else:
                need[k] = rest

    def pivot_rank(eid):
        unit = _unit_aspects(eid)
        gain = sum(min(unit.get(k, 0), v) for k, v in req.items())
        return (-gain, -len(_slots_opened_by(eid, action)))

    pivots = sorted((e for e in cards if _fits_slot(e, primaries[0])),
                    key=pivot_rank)[:12]
    for pivot in pivots:
        placed: dict[str, int] = {}
        agg: dict[str, int] = {}
        need = dict(req)
        apply(placed, agg, need, pivot, _useful_units(pivot, cards[pivot], need))
        queue = [dict(s) for s in primaries[1:]] + _slots_opened_by(pivot, action)
        steps = 0
        while queue and need and steps < 8:
            spec = queue.pop(0)
            steps += 1
            best, best_gain = None, 0
            for eid, qty in cards.items():
                avail = qty - placed.get(eid, 0)
                if avail <= 0 or not _fits_slot(eid, spec):
                    continue
                unit = _unit_aspects(eid)
                gain = sum(min(unit.get(k, 0), rest)
                           for k, rest in need.items())
                if gain > best_gain:
                    best_gain, best = gain, eid
            if best is None:
                continue
            avail = cards[best] - placed.get(best, 0)
            apply(placed, agg, need, best, _useful_units(best, avail, need))
            queue.extend(_slots_opened_by(best, action))
        if not need and all(agg.get(k, 0) < -v for k, v in neg.items()):
            return placed
    return None


def startable_recipes(action: str, cards: dict, limit: int = 6) -> list[dict]:
    """Craftable recipes of a verb whose requirements the given tabletop cards
    (eid -> quantity) can satisfy — first a cheap aggregate feasibility check,
    then a slot-level simulation so combinations that can't physically co-slot
    are dropped. Returns [{recipe, chosen}] ranked most-specific first."""
    matches, seen = [], set()
    for r in _recipes:
        if r["action"] != action or not r["craftable"] or r.get("hint"):
            continue
        sig = (tuple(sorted(r["req"].items())), tuple(sorted(r.get("neg", {}).items())))
        if sig in seen:
            continue
        if _match_requirements(r["req"], r.get("neg", {}), cards) is None:
            continue
        placed = _slot_sim(r["req"], r.get("neg", {}), action, cards)
        if placed is None:
            continue
        seen.add(sig)
        matches.append({"recipe": r, "chosen": placed})
    matches.sort(key=lambda m: -len(m["recipe"]["req"]))
    return matches[:limit]


def startable_lines(action: str, cards: dict, limit: int = 6) -> list[str]:
    """Human-readable '配方（用：卡…）' lines for startable_recipes."""
    lines = []
    for m in startable_recipes(action, cards, limit):
        used = " + ".join(f"{display_name(e)}×{n}" if n > 1 else display_name(e)
                          for e, n in m["chosen"].items())
        lines.append(tr(f"{recipe_name(m['recipe']['id'])}（用：{used}）",
                        f"{recipe_name(m['recipe']['id'])} (with {used})"))
    return lines


def element_aspects(entity_id: str) -> dict:
    """Aspects of an element as defined by the game (empty dict if unknown)."""
    return _el_aspects.get(entity_id.lower(), {})


def decays_to(entity_id: str) -> str:
    """What this element turns into when its timer runs out ('' = vanishes)."""
    return _decays.get(entity_id.lower(), "")


def element_lifetime(entity_id: str) -> int:
    """Natural lifetime in seconds (0 = permanent)."""
    return _lifetimes.get(entity_id.lower(), 0)


def decay_is_bad(entity_id: str) -> bool:
    """True when expiry turns the card into something harmful (ill health etc.)."""
    target = decays_to(entity_id)
    if not target:
        return False
    return bool(element_aspects(target).get("illhealth")) or target == "trace"


def decay_chain(entity_id: str, limit: int = 4) -> list[tuple[str, int]]:
    """Follow decayTo links: [(element, its lifetime), ...] starting from the
    card itself. Stops at a permanent element or after `limit` hops."""
    chain = []
    eid = entity_id.lower()
    seen = set()
    for _ in range(limit):
        if eid in seen:
            break
        seen.add(eid)
        chain.append((eid, element_lifetime(eid)))
        nxt = decays_to(eid)
        if not nxt:
            break
        eid = nxt
    return chain


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


def use_hint(entity_id: str, available: set | None = None,
             verbs: set | None = None) -> str:
    """Best craftable recipe consuming this card, as a one-line hint — the
    'so WHAT do I do with it' counterpart of obtain_hint. Prefers recipes
    whose other ingredients are already on the table."""
    eid = entity_id.lower()
    avail = {a.lower() for a in available} if available else set()
    best = None
    for i in _uses.get(eid, []):
        r = _recipes[i]
        if not r["craftable"] or r.get("hint"):
            continue
        missing = sum(1 for k in r["req"] if k != eid and k not in avail)
        gap = _verb_gap(r["action"], verbs)
        # Among payable recipes prefer the one consuming MORE of what's on
        # the table (pairing Fleeting with a live Fascination beats a solo
        # use), then the simpler one.
        mates_used = sum(1 for k in r["req"] if k != eid and k in avail)
        key = (gap, missing, -mates_used, len(r["req"]))
        if best is None or key < best[0]:
            best = (key, r)
    if best is None:
        return ""
    r = best[1]
    others = [display_name(k) for k in r["req"] if k != eid]
    mates = ("，配 " + " + ".join(others)) if others else ""
    mates_en = (" with " + " + ".join(others)) if others else ""
    return tr(f"用法：放入「{display_name(r['action'])}」{mates}（{recipe_name(r['id'])}）。",
              f"Use: {display_name(r['action'])}{mates_en} ({recipe_name(r['id'])}).")


def obtain_hint(entity_id: str, available: set | None = None,
                verbs: set | None = None) -> str:
    """Best craftable way, as a one-line hint for suggestions."""
    craftable = [r for r in _ranked_ways(entity_id, available, verbs) if r["craftable"]]
    if not craftable:
        return ""
    r = craftable[0]
    parts = [display_name(k) for k in r["req"]]
    inputs = " + ".join(parts) if parts else tr("直接开始", "start directly")
    return tr(f"获得方式：「{display_name(r['action'])}」+ {inputs}。",
              f"Obtain via {display_name(r['action'])} + {inputs}.")


_load()
