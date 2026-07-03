import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Token:
    id: str
    entity_id: str
    quantity: int
    position: tuple[float, float, float]
    sphere_path: str
    lifetime_remaining: float = 0.0
    defunct: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class ElementStack(Token):
    mutations: dict = field(default_factory=dict)
    illuminations: dict = field(default_factory=dict)


@dataclass
class Situation(Token):
    verb_id: str = ""
    recipe_id: str = ""
    state_identifier: int = 0
    time_remaining: float = 0.0
    is_open: bool = False
    thresholds: list = field(default_factory=list)


@dataclass
class GameState:
    character_name: str
    profession: str
    active_legacy: str
    version: str
    tokens: list[Token] = field(default_factory=list)
    # Dealer's draw piles, e.g. "seasonevents_draw" -> remaining season cards.
    draw_piles: dict[str, list[str]] = field(default_factory=dict)
    created_at: str = ""   # character DateTimeCreated — identifies one run
    ending_id: str = ""    # EndingTriggeredId, set once the run has ended
    raw: dict = field(default_factory=dict, repr=False)


def _token_from_command(tc: dict) -> Optional[Token]:
    payload = tc.get("Payload", {})
    location = tc.get("Location", {})
    pos = location.get("Anchored3DPosition") or location.get("LocalPosition") or {}
    sphere_path = location.get("AtSpherePath", {}).get("Path", "")

    common = {
        "id": payload.get("Id", ""),
        "entity_id": payload.get("EntityId", ""),
        "quantity": payload.get("Quantity", 1),
        "position": (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0)),
        "sphere_path": sphere_path,
        "lifetime_remaining": payload.get("LifetimeRemaining", 0.0),
        "defunct": tc.get("Defunct", False),
        "extra": tc,
    }

    pt = payload.get("$type", "")
    if "ElementStackCreationCommand" in pt:
        return ElementStack(
            **common,
            mutations=payload.get("Mutations", {}),
            illuminations=payload.get("Illuminations", {}),
        )
    elif "SituationCreationCommand" in pt:
        dominions = payload.get("Dominions", [])
        thresholds = []
        for d in dominions:
            if d.get("Identifier") == "RecipeThresholds":
                for s in d.get("Spheres", []):
                    spec = s.get("GoverningSphereSpec", {})
                    thresholds.append({
                        "id": spec.get("Id", ""),
                        "label": spec.get("Label", ""),
                        "required": spec.get("Required", {}),
                        "forbidden": spec.get("Forbidden", {}),
                        "greedy": spec.get("Greedy", False),
                        "consumes": spec.get("Consumes", False),
                        "action_id": spec.get("ActionId", ""),
                    })
        return Situation(
            **common,
            verb_id=payload.get("VerbId", ""),
            recipe_id=payload.get("CurrentRecipeId") or payload.get("RecipeId", ""),
            state_identifier=payload.get("StateIdentifier", 0),
            time_remaining=payload.get("TimeRemaining", 0.0),
            is_open=payload.get("IsOpen", False),
            thresholds=thresholds,
        )
    return Token(**common)


def _collect_tokens(sphere: dict, out: list) -> None:
    for tc in sphere.get("Tokens", []):
        token = _token_from_command(tc)
        if token:
            out.append(token)
    for tc in sphere.get("Tokens", []):
        payload = tc.get("Payload", {})
        for d in payload.get("Dominions", []):
            for s in d.get("Spheres", []):
                _collect_tokens(s, out)


def _parse_draw_piles(root: dict) -> dict[str, list[str]]:
    piles: dict[str, list[str]] = {}
    for sphere in (root.get("DealersTable") or {}).get("Spheres", []):
        pile_id = sphere.get("GoverningSphereSpec", {}).get("Id", "")
        if not pile_id:
            continue
        cards = [t.get("Payload", {}).get("EntityId", "")
                 for t in sphere.get("Tokens", [])]
        piles[pile_id] = [c for c in cards if c]
    return piles


def parse_save(path: str) -> GameState:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    char = (raw.get("CharacterCreationCommands") or [{}])[0]
    root = raw.get("RootPopulationCommand", {})

    tokens: list[Token] = []
    for sphere in root.get("Spheres", []):
        _collect_tokens(sphere, tokens)

    return GameState(
        character_name=char.get("Name", ""),
        profession=char.get("Profession", ""),
        active_legacy=char.get("ActiveLegacyId", ""),
        version=char.get("CreatedInVersion", {}).get("Version", ""),
        tokens=tokens,
        draw_piles=_parse_draw_piles(root),
        created_at=char.get("DateTimeCreated") or "",
        ending_id=char.get("EndingTriggeredId") or "",
        raw=raw,
    )


def find_situations(state: GameState, verb_id: Optional[str] = None) -> list[Situation]:
    result = [t for t in state.tokens if isinstance(t, Situation)]
    if verb_id:
        result = [t for t in result if t.verb_id == verb_id]
    return result


def find_stacks(state: GameState, entity_id: Optional[str] = None, sphere_path: str = "~/tabletop") -> list[ElementStack]:
    result = [t for t in state.tokens if isinstance(t, ElementStack)]
    if entity_id:
        result = [t for t in result if t.entity_id == entity_id]
    result = [t for t in result if t.sphere_path == sphere_path]
    return result


def has_stack(state: GameState, entity_id: str, min_qty: int = 1, sphere_path: str = "~/tabletop") -> bool:
    return sum(t.quantity for t in find_stacks(state, entity_id, sphere_path)) >= min_qty


def stack_quantity(state: GameState, entity_id: str, sphere_path: str = "~/tabletop") -> int:
    return sum(t.quantity for t in find_stacks(state, entity_id, sphere_path))


def find_stack(state: GameState, entity_id: str, sphere_path: str = "~/tabletop") -> Optional[ElementStack]:
    for t in find_stacks(state, entity_id, sphere_path):
        return t
    return None
