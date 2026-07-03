"""Suggestion engine: reads a parsed GameState and produces prioritized advice.

Pure logic, no window control — used by the GUI advisor. Card/verb names come
from the game's own localization via lexicon; rule text is bilingual via tr().
Rule sources: docs/strategy_knowledge.md, plus several rules ported from
autoccultist's brain-config (https://github.com/SunsetFi/autoccultist,
MIT License, Copyright 2020 RoboPhredDev): in-situation card counting,
season forecasting via the time verb's stored card, evidence/notoriety
warnings, decay-chain counters, and the opium emergency fallback.
Per-legacy opening guides are grounded in the game's own legacy recipe JSON
(legacy_*_recipes.json, DLC_*_recipes.json).
"""
from dataclasses import dataclass, field

from .save_parser import GameState, ElementStack, Situation, stack_quantity, find_situations
from .lexicon import display_name, recipe_name, situation_name, tr, get_language
from .knowledge import obtain_hint, has_aspect, element_aspects

TABLETOP = "~/tabletop"

# Countdown situations that end the game if they complete unanswered.
# verb_id -> list of counter card entity ids (any one works).
DANGER_VERBS = {
    "despair": ["contentment"],
    "visions": ["dread", "fleeting"],
}

# Other timed situations that can kill or end the run, with what to do.
# (verb_id, recipe_substrings or None for any recipe, priority, zh, en).
# Verb/recipe ids and counters verified against the game's recipe JSON
# (hazards.json, hunting.json, talking_2_interactions.json, time.json,
# long_recipes_attacks.json, ascension.json).
DOOM_SITUATIONS = [
    ("ambition", ("rival",), 195,
     "对手的飞升仪式已经开始，完成即是你的败北结局。立刻打断：刃系手下暗杀，或抢先完成自己的飞升。",
     "The rival's ascension rite is underway — if it completes, you lose. Interrupt it: "
     "an Edge follower's knife, or finish your own ascension first."),
    ("suspicion", ("pretrial", "trial", "question", "mitigation", "favour"), 190,
     "审判进行中！投入「当局欠下的人情」可免罪；没有人情则大概率失去手下，若受审的是你自己，定罪即游戏结束。",
     "A trial is in progress! Slot a Favour from the authorities to walk free; without one "
     "you'll likely lose the follower — and if the accused is you, conviction ends the game."),
    ("longassault.assassination", None, 185,
     "长生者派来的刺客动手了！投入手下抵挡（可能战死）或谋杀技能反制；若结算时没有健康/疲惫可失去，直接死亡。",
     "The Long's assassin strikes! Slot a follower to defend (they may die) or a murder skill; "
     "if no Health or Fatigue is free to lose when it resolves, you die."),
    ("long", ("confrontation",), 185,
     "与长生者的正面对决！需要强力手下或召唤物迎战；梦境对决还会吸走理性/激情，落败即结局。",
     "A confrontation with the Long! Field a strong follower or summon; the dream duel also "
     "devours Reason/Passion. Defeat is an ending."),
    ("poppytime", None, 175,
     "波比想要一个灵魂。投入一名手下满足她，否则倒计时结束就是「冬之献祭」结局。",
     "Poppy wants a soul. Feed her a follower, or the countdown ends in the Winter Sacrifice."),
    ("illhealth", ("sickness",), 155,
     "疾病正在夺取健康：确保桌面上留有健康或疲惫可被取走——全部被行动占用或已耗尽时会直接死亡。之后的病痛用入梦 + 资金/活力治疗。",
     "Sickness is coming for your Health: keep a Health or Fatigue card free on the table — "
     "if none can be taken, you die outright. Treat the affliction after with Dream + Funds/Vitality."),
    ("longassault", None, 150,
     "长生者正在袭击：视其策略可能抢劫资金、致伤、绑架手下或摧毁健康。收好资源，手下可投入防御。",
     "The Long is attacking: depending on their strategy they rob Funds, injure, abduct a "
     "follower or destroy Health. Guard your resources; a follower can defend."),
]

# Verbs the GUI should paint red while running.
ALERT_VERBS = set(DANGER_VERBS) | {v for v, *_ in DOOM_SITUATIONS}

# Fleeting fragments that upgrade an attribute when studied two at a time.
STUDY_PAIRS = {
    "vitality": "health",
    "erudition": "reason",
    "glimmering": "passion",
}

# Timed intermediate states that escalate if ignored: entity id -> (zh fix, en fix)
TIMED_AFFLICTIONS = {
    "affliction": ("入梦 + 1 资金或 1 活力治疗，超时会变成衰老（永久损失健康）。",
                   "Dream with 1 Funds or 1 Vitality; untreated it becomes Decrepitude (permanent Health loss)."),
    "restlessness": ("用绘画消耗或投入激情，超时会变成恐惧。",
                     "Spend it on Painting or Passion; untreated it becomes Dread."),
    "hunger": ("入梦 + 1 资金恢复，拖延会永久损失健康。",
               "Dream with 1 Funds; delay costs permanent Health."),
}

# Cards that eventually decay INTO dread — they count as future counters for visions.
FUTURE_DREAD = ("dread", "restlessness", "influencemoth")

# Cards whose decay is welcome or harmless — never nag "use it before it expires".
GOOD_RIDDANCE = {"dread", "fascination", "notoriety", "mystique", "restlessness",
                 "fatigue"}  # fatigue decays back into health

# Season forecast: season element id stored in the time verb -> per-season prep advice.
SEASON_PREP = {
    "seasondespair": "despair",
    "seasonvisions": "visions",
    "seasonsickness": "sickness",
    "seasonsuspicion": "suspicion",
    "seasonambitions": "ambitions",
}


@dataclass
class Suggestion:
    priority: int  # higher = more important
    title: str
    detail: str = ""
    urgent: bool = False


@dataclass
class ResourceRow:
    entity_id: str
    quantity: int
    min_lifetime: float  # 0 = permanent
    lifetimes: list[float] = field(default_factory=list)  # one per timed stack, ascending


@dataclass
class VerbRow:
    verb_id: str
    recipe_id: str
    time_remaining: float


@dataclass
class Advice:
    character: str = ""
    legacy: str = ""
    resources: list[ResourceRow] = field(default_factory=list)
    verbs: list[VerbRow] = field(default_factory=list)
    suggestions: list[Suggestion] = field(default_factory=list)


def _tabletop_stacks(state: GameState) -> list[ElementStack]:
    return [t for t in state.tokens
            if isinstance(t, ElementStack) and t.sphere_path == TABLETOP and not t.defunct]


def _all_stacks(state: GameState) -> list[ElementStack]:
    """Every live card, on the table or inside a situation (notes excluded)."""
    return [t for t in state.tokens
            if isinstance(t, ElementStack) and not t.defunct
            and not t.sphere_path.endswith("notessphere")]


def _stacks_in_situation(state: GameState, verb_id: str) -> list[ElementStack]:
    marker = f"!{verb_id}_"
    return [s for s in _all_stacks(state) if marker in s.sphere_path]


def _qty_anywhere(state: GameState, entity_id: str) -> int:
    return sum(s.quantity for s in _all_stacks(state) if s.entity_id == entity_id)


def _threat_count(state: GameState, threat: str, danger_verb: str) -> int:
    """Cards already eaten by the danger verb, plus table copies that will
    live long enough (>60s) to be eaten too. (Ported from autoccultist.)"""
    eaten = sum(s.quantity for s in _stacks_in_situation(state, danger_verb)
                if s.entity_id == threat)
    looming = sum(s.quantity for s in _tabletop_stacks(state)
                  if s.entity_id == threat
                  and (s.lifetime_remaining <= 0 or s.lifetime_remaining > 60))
    return eaten + looming


def _next_season(state: GameState):
    """The time verb stores the already-drawn next season card."""
    time_verb = next(iter(find_situations(state, "time")), None)
    if time_verb is None:
        return None, 0.0
    for s in _stacks_in_situation(state, "time"):
        if s.entity_id.startswith("season"):
            return s.entity_id, time_verb.time_remaining
    return None, time_verb.time_remaining


def _resources(state: GameState) -> list[ResourceRow]:
    grouped: dict[str, ResourceRow] = {}
    for s in _tabletop_stacks(state):
        row = grouped.setdefault(s.entity_id, ResourceRow(s.entity_id, 0, 0.0))
        row.quantity += s.quantity
        if s.lifetime_remaining > 0:
            row.lifetimes.append(s.lifetime_remaining)
    for row in grouped.values():
        row.lifetimes.sort()
        row.min_lifetime = row.lifetimes[0] if row.lifetimes else 0.0
    return sorted(grouped.values(), key=lambda r: r.entity_id)


def _verbs(state: GameState) -> list[VerbRow]:
    return [VerbRow(s.verb_id, s.recipe_id, s.time_remaining)
            for s in find_situations(state)]


def _counters_text(counter_ids: list[str]) -> str:
    if get_language() == "zh":
        return "或".join(f"「{display_name(c)}」" for c in counter_ids)
    return " or ".join(display_name(c) for c in counter_ids)


def _available(state: GameState) -> set:
    return {s.entity_id for s in _all_stacks(state)}


def _obtain_tip(state: GameState, entity_id: str) -> str:
    hint = obtain_hint(entity_id, _available(state))
    return ("" if not hint else tr("", " ") + hint)


def _qty_actionable(state: GameState, entity_id: str) -> int:
    """Copies the player can act on now: on the table or in an idle verb's
    output — but not locked inside a running verb."""
    running = [f"!{s.verb_id}_" for s in find_situations(state) if s.time_remaining > 0]
    return sum(s.quantity for s in _all_stacks(state)
               if s.entity_id == entity_id
               and not any(m in s.sphere_path for m in running))


THREAT_OF = {"despair": "dread", "visions": "fascination"}
COUNTERS_OF = {"despair": ["contentment"], "visions": list(FUTURE_DREAD) + ["fleeting"]}


def _danger_rules(state: GameState, out: list[Suggestion]):
    for s in find_situations(state):
        if s.verb_id not in DANGER_VERBS or s.time_remaining <= 0:
            continue
        counters = DANGER_VERBS[s.verb_id]
        threat = THREAT_OF[s.verb_id]
        name = situation_name(s.verb_id, s.recipe_id)
        inside = _stacks_in_situation(state, s.verb_id)
        eaten = sum(x.quantity for x in inside if x.entity_id == threat)
        # A counter already fed into the situation means it will resolve safely.
        if any(x.entity_id in counters for x in inside):
            out.append(Suggestion(
                priority=50,
                title=tr(f"「{name}」已投入对策卡，等待解除", f"{name} countered — resolving"),
                detail="",
            ))
            continue
        have = any(_qty_anywhere(state, c) for c in counters)
        cnames = _counters_text(counters if s.verb_id != "visions" else ["dread", "fleeting"])
        detail = tr(f"已吞 {eaten}/3 张「{display_name(threat)}」。放入 {cnames} 阻止，否则游戏结束。",
                    f"Holding {eaten}/3 {display_name(threat)}. Feed it {cnames} or the game ends.")
        if not have:
            if s.verb_id == "despair" and stack_quantity(state, "funds") >= 1:
                detail += tr("没有安逸时可以「入梦」+ 1 资金买鸦片酊救急。",
                             " No Contentment? Dream with 1 Funds to buy a Tincture of Opium.")
            elif s.verb_id == "visions" and stack_quantity(state, "passion") >= 1:
                detail += tr("没有恐惧时可以「入梦」+ 激情制造一张恐惧。",
                             " No Dread? Dream with Passion to develop one.")
            else:
                detail += tr("（一张对策卡都没有，想办法立刻弄一张！）",
                             " (No counter anywhere — get one NOW!)")
        out.append(Suggestion(
            priority=200,
            title=tr(f"危险！「{name}」倒计时 {s.time_remaining:.0f} 秒",
                     f"DANGER! {name} completes in {s.time_remaining:.0f}s"),
            detail=detail,
            urgent=True,
        ))

    # Spiral early warning: count cards already eaten plus long-lived table copies.
    # Skip when that danger verb is already counting down — the 200-alert covers it.
    active = {s.verb_id for s in find_situations(state)
              if s.verb_id in DANGER_VERBS and s.time_remaining > 0}
    for verb, threat in THREAT_OF.items():
        if verb in active:
            continue
        n = _threat_count(state, threat, verb)
        counters = COUNTERS_OF[verb]
        if n >= 2 and not any(_qty_anywhere(state, c) for c in counters):
            shown = ["contentment"] if verb == "despair" else ["dread", "fleeting"]
            pending = _season_pending(state, f"season{verb}")
            detail = tr(f"吸满 3 张就进入死亡倒计时，尽快准备 {_counters_text(shown)}。",
                        f"3 trigger the death countdown — get {_counters_text(shown)} ready.") \
                + _obtain_tip(state, shown[0])
            if not pending:
                detail += tr("（该时节本轮已抽完，重洗前不会被吸走，不必恐慌。）",
                             " (That season is out of the deck this cycle — no rush "
                             "until the reshuffle.)")
            out.append(Suggestion(
                priority=160 if pending else 40,
                title=tr(f"「{display_name(threat)}」已累计 {n} 张且没有对策卡",
                         f"{n}× {display_name(threat)} accumulated and no counter"),
                detail=detail,
                urgent=pending,
            ))


def _doom_rules(state: GameState, out: list[Suggestion]):
    """Timed situations beyond despair/visions that can end the run."""
    for s in find_situations(state):
        if s.time_remaining <= 0:
            continue
        for verb, recipe_keys, priority, zh, en in DOOM_SITUATIONS:
            if s.verb_id != verb:
                continue
            if recipe_keys and not any(k in (s.recipe_id or "") for k in recipe_keys):
                continue
            name = situation_name(s.verb_id, s.recipe_id)
            out.append(Suggestion(
                priority=priority,
                title=tr(f"危险！「{name}」倒计时 {s.time_remaining:.0f} 秒",
                         f"DANGER! {name} completes in {s.time_remaining:.0f}s"),
                detail=tr(zh, en),
                urgent=True,
            ))
            break


def _season_pending(state: GameState, season_id: str) -> bool:
    """Will this season still arrive before the deck reshuffles? The next season
    is already drawn into the time verb; the rest sit in the dealer's pile.
    Conservatively True when the save carries no pile data."""
    nxt, _ = _next_season(state)
    if nxt == season_id:
        return True
    pile = state.draw_piles.get("seasonevents_draw")
    if pile is None:
        return True
    return season_id in pile


def _season_deck_rules(state: GameState, out: list[Suggestion]):
    """Show what the seasons deck still holds this cycle (it reshuffles empty)."""
    pile = state.draw_piles.get("seasonevents_draw")
    if pile is None:
        return
    if not pile:
        out.append(Suggestion(14,
            tr("时节牌库已抽空，即将重洗", "Seasons deck empty — reshuffle imminent"),
            tr("重洗后所有时节重新入库（包括绝望和幻象）。",
               "Every season returns to the deck, Despair and Visions included.")))
        return
    counts: dict[str, int] = {}
    for c in pile:
        counts[c] = counts.get(c, 0) + 1
    if get_language() == "zh":
        listing = "、".join(f"{display_name(c)}×{n}" for c, n in counts.items())
    else:
        listing = ", ".join(f"{n}× {display_name(c)}" for c, n in counts.items())
    nxt, _ = _next_season(state)
    gone = [f"season{v}" for v in ("despair", "visions")
            if f"season{v}" not in counts and nxt != f"season{v}"]
    detail = listing + tr("。", ".")
    if gone:
        names = "、".join(display_name(g) for g in gone) if get_language() == "zh" \
            else " / ".join(display_name(g) for g in gone)
        detail += tr(f"{names}本轮已抽完，重洗前不会再来。",
                     f" {names} won't come again until the reshuffle.")
    out.append(Suggestion(14,
        tr(f"本轮时节牌库还剩 {len(pile)} 张", f"Seasons left this cycle: {len(pile)}"),
        detail))


def _season_forecast_rules(state: GameState, out: list[Suggestion]):
    """The next season is knowable in advance — warn if we're unprepared for it."""
    season, eta = _next_season(state)
    if not season:
        return
    name = display_name(season)
    kind = SEASON_PREP.get(season)
    unready = False
    if kind == "despair":
        unready = _threat_count(state, "dread", "despair") > 0 \
            and not _qty_anywhere(state, "contentment")
        prep = tr("场上有恐惧但没有安逸，时节一到就会被吸走。",
                  "Dread on the table and no Contentment — it will be devoured on arrival.") \
            + _obtain_tip(state, "contentment")
    elif kind == "visions":
        unready = _threat_count(state, "fascination", "visions") > 0 \
            and not any(_qty_anywhere(state, c) for c in COUNTERS_OF["visions"])
        prep = tr("场上有入迷但没有恐惧/一瞬追忆。",
                  "Fascination on the table and no Dread/Fleeting Reminiscence.") \
            + _obtain_tip(state, "fleeting")
    elif kind == "sickness":
        unready = not stack_quantity(state, "funds") and not stack_quantity(state, "vitality")
        prep = tr("既无资金也无活力，病痛来了没法治。",
                  "No Funds and no Vitality — you can't treat the affliction.")
    elif kind == "suspicion":
        unready = any(_qty_anywhere(state, e) for e in ("mystique", "notoriety", "evidence", "evidenceb"))
        prep = tr("场上有声名/证据，时节一到会招来猎人或升级证据。",
                  "Reputation/evidence on the table — hunters or evidence upgrades incoming.")
    elif kind == "ambitions":
        pos = _ascension_position(state)
        if pos and pos[1] in "cde" and pos[0] in TRIBUTE:
            track = pos[0]
            if track == "power":
                unready = stack_quantity(state, "funds") < 1
            else:
                unready = not any(has_aspect(s.entity_id, "prisoner")
                                  for s in _all_stacks(state))
            zh_t, en_t = TRIBUTE[track]
            prep = tr(f"欲望卡会被吸走考验升级，需献上{zh_t}——现在还没备齐，备不上会产生躁动。",
                      f"The season devours the desire card and demands {en_t} — none ready; "
                      "failing breeds Restlessness.")
        else:
            prep = ""
    else:
        prep = ""
    out.append(Suggestion(
        priority=170 if unready else 15,
        title=tr(f"时节预报：「{name}」约 {eta:.0f} 秒后到来",
                 f"Season forecast: {name} in ~{eta:.0f}s"),
        detail=prep if unready else "",
        urgent=unready,
    ))


def _best_follower_aspect(state: GameState, aspect: str) -> int:
    """Highest value of an aspect among followers on the table."""
    return max((element_aspects(s.entity_id).get(aspect, 0)
                for s in _tabletop_stacks(state)
                if has_aspect(s.entity_id, "follower")), default=0)


def _evidence_dispatch_tip(state: GameState) -> str:
    """Concrete destroy-evidence plan. Tiers from hunting_countermeasures.json
    (talk = follower + evidence; moth 5 / moth 1 / bare hands)."""
    moth = _best_follower_aspect(state, "moth")
    if moth >= 5:
        return tr("你有蛾系 5+ 的手下：谈话 = 手下 + 证据，约七成销毁。",
                  " A Moth-5 follower is on hand: talk = follower + evidence, ~70% to destroy.")
    if moth >= 1:
        return tr("手下蛾系仅入门：销毁只有约三成，失败会折损手下并 +1 邪名，慎重。",
                  " Your best Moth is minor: ~30% only, and failure costs the follower "
                  "plus 1 Notoriety.")
    return tr("没有蛾系手下——徒手销毁把握很低，先培养一名蛾系门徒。",
              " No Moth follower — bare-handed odds are poor; raise a Moth disciple first.")


def _reputation_rules(state: GameState, out: list[Suggestion]):
    if _qty_anywhere(state, "evidenceb"):
        out.append(Suggestion(
            priority=190,
            title=tr(f"「{display_name('evidenceb')}」在场！", f"{display_name('evidenceb')} exists!"),
            detail=tr("被审判即游戏结束。销毁它，或准备「当局欠下的人情」。",
                      "A trial ends the game. Destroy it, or hold a Favour.")
            + _evidence_dispatch_tip(state),
            urgent=True,
        ))
    elif _qty_anywhere(state, "evidence"):
        out.append(Suggestion(
            priority=125,
            title=tr(f"「{display_name('evidence')}」在场", f"{display_name('evidence')} on the table"),
            detail=tr("下个疑心时节可能升级为确凿证据，尽快销毁。",
                      "Next Suspicion season may upgrade it — destroy it soon.")
            + _evidence_dispatch_tip(state),
            urgent=True,
        ))
    n = stack_quantity(state, "notoriety")
    if n:
        out.append(Suggestion(
            priority=95,
            title=tr(f"{n} 张「{display_name('notoriety')}」在场", f"{n}× {display_name('notoriety')} on the table"),
            detail=tr("疑心时节会用它生成猎人/证据。等它自然衰变并避免再产生；搬去新总部可消 1 张，"
                      "G&G 高层职位每次上班也会吸走 1 张。",
                      "Suspicion seasons turn it into hunters/evidence. Let it decay and stop "
                      "making more; moving HQ absorbs one, and the top Glover & Glover post "
                      "eats one per shift."),
        ))
    _hunter_rules(state, out)


def _hunter_rules(state: GameState, out: list[Suggestion]):
    """A hunter on the table — lay out the counterplays with real odds.
    Tiers from hunting_countermeasures.json: edge/winter 10 / 5 / 1 / none;
    Dread breaks grim hunters, Fascination the idealists."""
    hunter = next((s.entity_id for s in _tabletop_stacks(state)
                   if has_aspect(s.entity_id, "hunter")), None)
    if not hunter:
        return
    edge = _best_follower_aspect(state, "edge")
    winter = _best_follower_aspect(state, "winter")
    tier = max(edge, winter)
    kind = tr("刃", "Edge") if edge >= winter else tr("冬", "Winter")
    if tier >= 10:
        plan = tr(f"你有{kind} 10+ 的手下：谈话 = 手下 + 猎人，必成。",
                  f"Your {kind}-10 follower ends this: talk = follower + hunter, guaranteed.")
    elif tier >= 5:
        plan = tr(f"最佳手下{kind} {tier}：袭击约七成，失败折损手下并 +1 邪名。",
                  f"Best follower has {kind} {tier}: ~70% kill; failure costs them and adds Notoriety.")
    elif tier >= 1:
        plan = tr(f"手下{kind}系太弱（{tier}）：袭击仅约三成，另可考虑谈话劝退。",
                  f"Followers are weak in {kind} ({tier}): ~30% only — consider talking instead.")
    else:
        plan = tr("没有刃/冬系手下，硬拼只有一成。",
                  "No Edge/Winter follower — a bare attack is ~10%.")
    talk = tr("冷峻的猎人怕「恐惧」、理想主义者怕「入迷」，谈话时塞给他也能劝退。",
              " Grim hunters break on Dread, idealists on Fascination — slip one in when talking.")
    out.append(Suggestion(
        priority=120,
        title=tr(f"猎人「{display_name(hunter)}」在场", f"Hunter {display_name(hunter)} is prowling"),
        detail=tr("他会持续收集证据。", "They keep gathering evidence. ") + plan + talk,
        urgent=True,
    ))


def _affliction_rules(state: GameState, out: list[Suggestion]):
    for eid, (zh_fix, en_fix) in TIMED_AFFLICTIONS.items():
        for s in _tabletop_stacks(state):
            if s.entity_id == eid:
                out.append(Suggestion(
                    priority=140,
                    title=tr(f"「{display_name(eid)}」在场（约 {s.lifetime_remaining:.0f} 秒后恶化）",
                             f"{display_name(eid)} on the table (worsens in ~{s.lifetime_remaining:.0f}s)"),
                    detail=tr(zh_fix, en_fix),
                    urgent=s.lifetime_remaining <= 30,
                ))


def _pair_study_rules(state: GameState, out: list[Suggestion]) -> set[str]:
    """Suggest studying skill fragments two at a time; returns entity ids covered."""
    covered = set()
    for eid, attr in STUDY_PAIRS.items():
        stacks = [s for s in _tabletop_stacks(state) if s.entity_id == eid]
        total = sum(s.quantity for s in stacks)
        if total < 2:
            continue
        lives = sorted(s.lifetime_remaining for s in stacks if s.lifetime_remaining > 0)
        soonest = lives[0] if lives else 0.0
        expiring = 0 < soonest <= 60
        detail = tr(f"两张一起放入「{display_name('study')}」可获得升级「{display_name(attr)}」的课程。",
                    f"Study two together for a lesson toward upgrading {display_name(attr)}.")
        if expiring:
            detail += tr(f"最快的一张约 {soonest:.0f} 秒后消失，抓紧！",
                         f" Soonest expires in ~{soonest:.0f}s — hurry!")
            covered.add(eid)
        out.append(Suggestion(
            priority=130 if expiring else 70,
            title=tr(f"凑齐了 {total} 张「{display_name(eid)}」，可以合成研读",
                     f"{total}× {display_name(eid)} — study two together"),
            detail=detail,
            urgent=0 < soonest <= 30,
        ))
    return covered


def _generic_rules(state: GameState, out: list[Suggestion]):
    _danger_rules(state, out)
    _doom_rules(state, out)
    _season_forecast_rules(state, out)
    _season_deck_rules(state, out)
    _reputation_rules(state, out)
    _affliction_rules(state, out)
    covered = _pair_study_rules(state, out)

    # Aggregate expiring cards per entity so "2 vitality about to rot" is one line.
    expiring: dict[str, list[float]] = {}
    for s in _tabletop_stacks(state):
        if 0 < s.lifetime_remaining <= 60 and s.entity_id not in covered \
                and s.entity_id not in TIMED_AFFLICTIONS \
                and s.entity_id not in GOOD_RIDDANCE:
            expiring.setdefault(s.entity_id, []).append(s.lifetime_remaining)
    for eid, lives in expiring.items():
        soonest = min(lives)
        n = len(lives)
        name = display_name(eid)
        head = tr(f"{n} 张「{name}」", f"{n}× {name}") if n > 1 else tr(f"「{name}」", name)
        out.append(Suggestion(
            priority=150 if soonest <= 20 else 80,
            title=tr(f"{head} 即将消失（最快约 {soonest:.0f} 秒）",
                     f"{head} expiring (soonest ~{soonest:.0f}s)"),
            detail=tr("尽快使用，否则会腐朽/消散。", "Use it before it decays."),
            urgent=soonest <= 20,
        ))

    # Money watermark: 1 Funds drains every 60s. (Exile uses cash, not funds.)
    funds = stack_quantity(state, "funds")
    if (state.active_legacy or "").startswith("exile"):
        pass
    elif funds < 3:
        out.append(Suggestion(
            priority=145 if funds == 0 else 90,
            title=tr(f"资金只剩 {funds}（每 60 秒消耗 1）",
                     f"Only {funds} Funds left (1 drains every 60s)"),
            detail=tr("断粮会扣健康且难以恢复，优先赚钱。",
                      "Starvation converts Health and is hard to undo — earn money now."),
            urgent=funds == 0,
        ))
    elif funds >= 30:
        out.append(Suggestion(
            priority=10,
            title=tr(f"资金充裕（{funds}），可以少花时间赚钱了",
                     f"Funds are plentiful ({funds}) — ease off the grind"),
            detail=tr("这不是资本主义模拟器，把行动格腾给推进目标的事。",
                      "This is not capitalism simulator — spend your verbs on progress instead."),
        ))

    _idle_verb_rules(state, out)


def _best_idle_use(state: GameState, verb_id: str):
    """First matching (zh, en) recommendation for an idle verb, or None."""
    has = lambda e: stack_quantity(state, e) > 0
    n = lambda e: stack_quantity(state, e)

    if verb_id == "dream":
        if has("affliction") and (has("funds") or has("vitality")):
            return (f"病痛 + 资金/活力：治疗病痛", "affliction + Funds/Vitality: heal it")
        if has("hunger") and has("funds"):
            return (f"饥饿 + 资金：恢复", "Hunger + Funds: recover")
        if has("dread") and has("contentment"):
            return (f"恐惧 + 安逸：消除恐惧", "Dread + Contentment: clear the Dread")
        if has("fascination") and has("dread"):
            return (f"入迷 + 恐惧：换成更安全的一瞬追忆",
                    "Fascination + Dread → safer Fleeting Reminiscence")
        for way in ("waypeacock", "wayspider", "waystag_after", "waywhite", "waywood"):
            if has(way):
                return (f"用「{display_name(way)}」深入漫宿（拿影响和秘史）",
                        f"walk {display_name(way)} into the Mansus for influences and histories")
        if has("health"):
            return (f"健康：早睡早起（产一瞬追忆，备着克幻象时节）",
                    "Health: early nights → Fleeting Reminiscence, insurance against Visions")
        if has("passion"):
            return (f"激情：入梦推进漫宿（林地）", "Passion: dream toward the Wood")
    elif verb_id == "work":
        for job in ("job", "introjob", "legacyphysicianjob", "institutephysicianjob",
                    "legacydetectivejob", "legacybytjob", "legacybytjobmatured",
                    "ghouljob.first", "ghouljob"):
            if has(job):
                return (f"放入「{display_name(job)}」上班赚钱", f"slot {display_name(job)} and get paid")
        for job, mate in (("priestjob", "passion"), ("priestjob", "reason"),
                          ("legacydancerjob", "health")):
            if has(job) and has(mate):
                return (f"「{display_name(job)}」+「{display_name(mate)}」赚钱",
                        f"{display_name(job)} + {display_name(mate)} for pay")
        if has("health"):
            return (f"健康：体力活（资金 + 活力；活力凑 2 张可升健康）",
                    "Health: labour → Funds + Vitality (pair Vitality to raise Health)")
        if has("passion"):
            return (f"激情：绘画（产灵感，注意会积累声名）",
                    "Passion: paint → Glimmering (mind the reputation)")
    elif verb_id == "study":
        for frag, attr in STUDY_PAIRS.items():
            if n(frag) >= 2:
                return (f"「{display_name(frag)}」×2：升级「{display_name(attr)}」",
                        f"{display_name(frag)} ×2: upgrade {display_name(attr)}")
        lore_counts: dict[str, int] = {}
        for s in _tabletop_stacks(state):
            if s.entity_id.startswith("fragment"):
                lore_counts[s.entity_id] = lore_counts.get(s.entity_id, 0) + s.quantity
        for eid, count in lore_counts.items():
            if count >= 2:
                return (f"「{display_name(eid)}」×2：合成更高级秘传",
                        f"{display_name(eid)} ×2: combine into higher lore")
        for s in _tabletop_stacks(state):
            if s.entity_id.startswith(("book", "textbook")):
                return (f"阅读「{display_name(s.entity_id)}」",
                        f"read {display_name(s.entity_id)}")
        if has("passion"):
            return (f"激情：冥想（产灵感，凑 2 张可升激情）",
                    "Passion: exercise it → Glimmering (pair up to raise Passion)")
        if has("reason"):
            return (f"理性：冥想（产博闻，凑 2 张可升理性）",
                    "Reason: exercise it → Erudition (pair up to raise Reason)")
    elif verb_id == "talk":
        believer = next(
            (s.entity_id for s in _tabletop_stacks(state)
             if has_aspect(s.entity_id, "follower") and not has_aspect(s.entity_id, "disciple")),
            None)
        if believer and any(s.entity_id.startswith("fragment") for s in _tabletop_stacks(state)):
            return (f"用秘传把「{display_name(believer)}」提升为门徒（办事成功率更高）",
                    f"raise {display_name(believer)} to disciple with lore (better odds on jobs)")
        acq = next((s.entity_id for s in _tabletop_stacks(state)
                    if has_aspect(s.entity_id, "acquaintance")), None)
        if acq:
            return (f"与「{display_name(acq)}」交谈（配秘传碎片可引荐入教）",
                    f"chat with {display_name(acq)} (add lore to recruit them)")
    elif verb_id == "explore":
        for s in _tabletop_stacks(state):
            if s.entity_id.startswith("vault."):
                return (f"远征「{display_name(s.entity_id)}」：先派 1 雇员 + 1 资金侦察",
                        f"expedition to {display_name(s.entity_id)}: scout with a hireling + 1 Funds first")
        for s in _tabletop_stacks(state):
            if s.entity_id.startswith("fragmentsecrethistories"):
                return (f"「{display_name(s.entity_id)}」：寻找藏宝地",
                        f"{display_name(s.entity_id)}: locate a vault")
        if has("funds"):
            return (f"资金：探索城市（发现地点/雇员）",
                    "Funds: explore the city for locations and hirelings")
    return None


def _idle_verb_rules(state: GameState, out: list[Suggestion]):
    idle = [s for s in find_situations(state)
            if s.time_remaining <= 0 and s.verb_id != "time"]
    for s in idle:
        best = _best_idle_use(state, s.verb_id)
        name = display_name(s.verb_id)
        if best:
            out.append(Suggestion(
                priority=45,
                title=tr(f"「{name}」空闲，建议：{best[0]}", f"{name} idle — try: {best[1]}"),
            ))
        else:
            out.append(Suggestion(
                priority=30,
                title=tr(f"「{name}」空闲中", f"{name} is idle"),
                detail=tr("有空闲的行动格，别让它闲着。", "An action slot is free — keep it busy."),
            ))


# --------------------------------------------------------- opening guides ---
# Per-legacy walkthroughs keyed to the legacy's own plot cards, so each rule
# retires itself once the card is consumed. Numbers come from the game's
# recipe JSON (legacy_*_recipes.json / DLC_*_recipes.json).

def _opening_aspirant(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    if q("introjob"):
        out.append(Suggestion(120,
            tr(f"开局第一步：把「{display_name('introjob')}」放入「{display_name('work')}」",
               f"First move: put {display_name('introjob')} into {display_name('work')}"),
            tr("10 秒结束，获得 2 资金和 1 健康；随后会自动入梦醒来（得激情和安逸），遗赠也会寄到「研读」。",
               "10s for 2 Funds and 1 Health; the intro dream (Passion + Contentment) "
               "and the bequest in Study follow on their own.")))
    if q("bequestintro"):
        out.append(Suggestion(115,
            tr(f"关键抉择：研读「{display_name('bequestintro')}」",
               f"Key choice: study {display_name('bequestintro')}"),
            tr("配理性 → 启明野心 + 灯之秘传（稳健学者路线）；配激情 → 权力野心 + 铸之秘传。"
               "两条路都附送书商的地址，之后就能探索买书了。",
               "With Reason → Enlightenment ambition + Lantern lore (the steady scholar route); "
               "with Passion → Power ambition + Forge lore. Either way you also get the book "
               "dealer's address for later exploring.")))
    if q("contactintro"):
        out.append(Suggestion(65,
            tr(f"「{display_name('contactintro')}」：研读它会产生 1 张秘氛",
               f"{display_name('contactintro')}: studying it yields 1 Mystique"),
            tr("秘氛在疑心时节会招来猎人，读完记得留意声名。",
               "Mystique draws hunters in Suspicion seasons — mind your reputation afterwards.")))


def _opening_detective(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    if q("legacydetectivejob"):
        out.append(Suggestion(120,
            tr(f"开局第一步：把「{display_name('legacydetectivejob')}」放入「{display_name('work')}」",
               f"First move: put {display_name('legacydetectivejob')} into {display_name('work')}"),
            tr("10 秒结束，获得 3 资金和 1 健康，并解锁其余行动格。",
               "10s for 3 Funds and 1 Health, and it unlocks the other verbs.")))
    if q("myevidenceb"):
        out.append(Suggestion(110,
            tr(f"破案！把「{display_name('myevidenceb')}」放入警探工作",
               f"Solve the case: slot {display_name('myevidenceb')} into your detective work"),
            tr("结案得资金并清掉当前案件；若加一名可靠证人可得 7 资金 + 当局欠下的人情（免罪王牌）。",
               "Closing pays Funds and clears the case; add a reliable witness for 7 Funds "
               "plus a Favour from the authorities (your get-out-of-trial card).")))
    else:
        # A case is any card with the "suspicious" aspect: a troublemaker
        # (element ids end in "_r") or tentative evidence.
        case = next((s.entity_id for s in _tabletop_stacks(state)
                     if s.entity_id.endswith("_r") or s.entity_id == "myevidence"), None)
        if case and q("legacydetectivejob_matured"):
            out.append(Suggestion(100,
                tr(f"调查案件：警探工作 +「{display_name(case)}」+ 理性",
                   f"Investigate: detective job + {display_name(case)} + Reason"),
                tr("60 秒得资金和线索；理性放得越多越容易直接得到确凿线索。",
                   "60s for Funds and evidence; more Reason means better odds of conclusive evidence.")))
    plotitem = next((e for e in ("legacydetective_plotitem", "legacydetective_plotitem_backup")
                     if q(e)), None)
    if plotitem:
        out.append(Suggestion(85,
            tr(f"注意：「{display_name(plotitem)}」是双刃剑",
               f"Careful with {display_name(plotitem)}"),
            tr("研读它推进主线，但会同时产生入迷和恐惧——先备好对策卡再读。",
               "Studying it advances the story but yields both Fascination and Dread — "
               "have counters ready first.")))


def _opening_byt(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    if q("legacybytjob"):
        out.append(Suggestion(120,
            tr(f"开局第一步：把「{display_name('legacybytjob')}」放入「{display_name('work')}」",
               f"First move: put {display_name('legacybytjob')} into {display_name('work')}"),
            tr("10 秒得 3 资金，之后每次挥霍继续来钱，并解锁其余行动格。",
               "10s for 3 Funds; the dissolute life keeps paying after, and other verbs unlock.")))
    if q("legacydiarylastcharacter"):
        out.append(Suggestion(105,
            tr(f"研读「{display_name('legacydiarylastcharacter')}」",
               f"Study {display_name('legacydiarylastcharacter')}"),
            tr("获得 1 理性和一份杯之秘传——你的第一份秘传。",
               "Yields 1 Reason and a Grail lore fragment — your first lore.")))
    if q("legacybytjobmatured"):
        out.append(Suggestion(70,
            tr(f"「{display_name('legacybytjobmatured')}」不是长久之计",
               f"{display_name('legacybytjobmatured')} won't last"),
            tr("每次 30 秒 3 资金，但迟早会终结（终结后另有一笔安家费）。趁现在有钱，买书升属性建立自己的收入。",
               "3 Funds per 30s, but it ends eventually (with a final settlement). "
               "Use the money now: buy books and raise skills before it dries up.")))


def _opening_physician(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    if q("legacyphysicianjob"):
        out.append(Suggestion(120,
            tr(f"开局第一步：把「{display_name('legacyphysicianjob')}」放入「{display_name('work')}」",
               f"First move: put {display_name('legacyphysicianjob')} into {display_name('work')}"),
            tr("10 秒得 2 资金、1 健康、理性直接升到 3 张，并换来研究所的固定职位（60 秒 2 资金，开局最稳收入）。",
               "10s for 2 Funds, 1 Health, Reason up to 3, and the Institute post "
               "(2 Funds per 60s — the steadiest early income in the game).")))
    if q("legacyphysiciannotes"):
        out.append(Suggestion(105,
            tr(f"研读「{display_name('legacyphysiciannotes')}」",
               f"Study {display_name('legacyphysiciannotes')}"),
            tr("获得书商的地址——之后用「探索」+ 资金去买书。",
               "Yields the book dealer's address — explore with Funds to buy books next.")))


def _opening_dancer(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    if q("legacydancerjob") and q("health"):
        out.append(Suggestion(110,
            tr(f"跳舞赚钱：「{display_name('legacydancerjob')}」+ 健康放入「{display_name('work')}」",
               f"Dance for pay: {display_name('legacydancerjob')} + Health into {display_name('work')}"),
            tr("45 秒 1 资金；再塞 2 张心或蛾的影响可以多拿小费。",
               "1 Funds per 45s; slot 2 Heart or Moth influences on top for tips.")))
    if q("dancerlegacy_plotitem_a"):
        out.append(Suggestion(105,
            tr(f"研读「{display_name('dancerlegacy_plotitem_a')}」+ 心/蛾影响",
               f"Study {display_name('dancerlegacy_plotitem_a')} with a Heart/Moth influence"),
            tr("配心之影响 → 2 张活力（升健康）；配蛾之影响 → 2 张灵感（升激情）。正好凑一对直接升级属性。",
               "With Heart → 2 Vitality (toward Health); with Moth → 2 Glimmering (toward Passion). "
               "Either pair upgrades an attribute in one go.")))


def _opening_priest(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    if q("priestjob") and not _qty_anywhere(state, "reason"):
        out.append(Suggestion(120,
            tr(f"开局第一步：「{display_name('priestjob')}」+ 激情放入「{display_name('work')}」",
               f"First move: {display_name('priestjob')} + Passion into {display_name('work')}"),
            tr("10 秒得 1 资金和 1 理性；之后职业配激情或理性都能持续赚钱。",
               "10s for 1 Funds and 1 Reason; afterwards the post pays with either Passion or Reason.")))
    if q("priestjob") and _qty_anywhere(state, "fragmentknock") \
            and not _qty_anywhere(state, "fervour"):
        out.append(Suggestion(75,
            tr(f"布道体系：职业 + 理性 + 启之秘传 → 「{display_name('fervour')}」",
               f"Preaching: post + Reason + Knock lore → {display_name('fervour')}"),
            tr("狂热再配秘传和属性布道，赚钱比普通工作快。",
               "Fervour plus lore and an ability preaches for better pay than plain work.")))


def _opening_ghoul(state: GameState, out: list[Suggestion]):
    q = lambda e: _qty_actionable(state, e)
    memories = [("memory.shameful", tr("6 资金 + 激情 + 人情", "6 Funds + Passion + a Favour")),
                ("memory.profitable", tr("6 资金 + 理性", "6 Funds + Reason")),
                ("memory.joyful", tr("4 资金 + 健康", "4 Funds + Health"))]
    held = [(e, gain) for e, gain in memories if q(e)]
    if q("ghouljob.first") and held:
        lines = "；".join(f"「{display_name(e)}」→ {gain}" for e, gain in held) \
            if get_language() == "zh" else \
            "; ".join(f"{display_name(e)} → {gain}" for e, gain in held)
        out.append(Suggestion(115,
            tr(f"通灵会：「{display_name('ghouljob.first')}」+ 一张回忆放入「{display_name('work')}」",
               f"Séance: {display_name('ghouljob.first')} + one memory into {display_name('work')}"),
            tr(f"{lines}。每次通灵都产生 1 秘氛，攒多了小心疑心时节。",
               f"{lines}. Each séance also yields 1 Mystique — watch it before Suspicion seasons.")))


def _opening_exile(state: GameState, out: list[Suggestion]):
    if _qty_actionable(state, "ticket.train"):
        out.append(Suggestion(120,
            tr(f"开局第一步：把「{display_name('ticket.train')}」放入「{display_name('use')}」",
               f"First move: put {display_name('ticket.train')} into {display_name('use')}"),
            tr("动身离开，流亡从这里开始。", "Board the train — the exile begins here.")))
    out.append(Suggestion(12,
        tr("流亡者模式规则与本体不同",
           "The Exile plays by different rules"),
        tr("没有研读/入梦/时节牌库，军师的常规建议大多不适用。核心循环是移动—整备—行动，"
           "留下的「痕迹」会引来仇敌的爪牙，换城市可以甩掉他们。",
           "No Study/Dream/seasons deck, so most of the advisor's standard rules don't apply. "
           "The loop is move — prepare — act; the Trace you leave draws your foe's servants, "
           "and moving city shakes them off.")))


# Continuation starts reuse another legacy's opening cards.
OPENING_ALIASES = {
    "survivor": "aspirant",
    "cousin": "aspirant",
    "detectivepostpromotion": "detective",
}

OPENING_GUIDES = {
    "aspirant": _opening_aspirant,
    "detective": _opening_detective,
    "brightyoungthing": _opening_byt,
    "physician": _opening_physician,
    "dancer": _opening_dancer,
    "priest": _opening_priest,
    "ghoul": _opening_ghoul,
    "exile": _opening_exile,
}


def _is_opening(state: GameState) -> bool:
    """Still the basic-cards stage: no attribute has been upgraded yet."""
    return not any(s.entity_id.startswith("skill") for s in _all_stacks(state))


def _opening_rules(state: GameState, out: list[Suggestion]):
    legacy = state.active_legacy or ""
    canon = OPENING_ALIASES.get(legacy, legacy)
    if canon.startswith("exile"):
        canon = "exile"
    guide = OPENING_GUIDES.get(canon)
    if guide:
        guide(state, out)
    if canon != "exile" and _is_opening(state):
        out.append(Suggestion(55,
            tr("开局阶段目标：稳经济 → 升属性 → 攒秘传",
               "Opening goals: income → attributes → lore"),
            tr("① 保持资金 ≥5；② 冥想/工作攒 2 张同类碎片升级属性（健康优先，疾病时节风险大）；"
               "③ 买书研读攒秘传；④ 凑齐熟人 + 2 级秘传就能建教团。",
               "1) Keep Funds at 5+. 2) Meditate/work up pairs of skill fragments to raise "
               "attributes (Health first — Sickness seasons hurt). 3) Buy and study books for lore. "
               "4) An Acquaintance + 2nd-level lore founds your cult.")))


# ------------------------------------------------------- progression rules ---
# Mid/late game: cult founding, the ambition track, Mansus ways, expeditions,
# rival Longs. Grounded in culting.json / ascension.json / mansus.json /
# followers.json; aspect checks go through the knowledge element index.

# Lore fragment ids encode aspect + level: fragment<aspect>[suffix].
LORE_KINDS = ("secrethistories", "edge", "forge", "grail", "heart",
              "knock", "lantern", "moth", "winter")
LORE_SUFFIX_LEVEL = {"": 2, "b": 4, "c": 6, "d": 8, "e": 10, "f": 12, "g": 14}

ASCENSION_TRACKS = ("enlightenment", "sensation", "power", "change")
ASCENSION_LORE = {"power": "forge", "enlightenment": "lantern", "sensation": "grail"}
# What Ambition seasons demand at desire 3+ (strategy_knowledge.md §9).
TRIBUTE = {
    "power": ("资金", "Funds"),
    "enlightenment": ("囚徒", "a prisoner"),
    "sensation": ("尸体、疯子或囚徒", "a corpse, madman or prisoner"),
}


def _lore_levels(state: GameState) -> dict[str, int]:
    """Lore aspect -> highest fragment level held anywhere."""
    best: dict[str, int] = {}
    for s in _all_stacks(state):
        if not s.entity_id.startswith("fragment"):
            continue
        rest = s.entity_id[len("fragment"):]
        for kind in LORE_KINDS:
            if rest.startswith(kind):
                lvl = LORE_SUFFIX_LEVEL.get(rest[len(kind):])
                if lvl:
                    best[kind] = max(best.get(kind, 0), lvl)
                break
    return best


def _ascension_position(state: GameState):
    """(track, stage a-g, entity_id) of the furthest ambition card, or None."""
    order = "abcdefg"
    best = None
    for s in _all_stacks(state):
        eid = s.entity_id
        if not eid.startswith("ascension") or eid.startswith("ascensionlesson"):
            continue
        rest = eid[len("ascension"):]
        for track in ASCENSION_TRACKS:
            if rest.startswith(track):
                stage = rest[len(track):][:1]  # bm/bf -> b
                if stage in order and (best is None or order.index(stage) > order.index(best[1])):
                    best = (track, stage, eid)
                break
    return best


def _rival_rules(state: GameState, out: list[Suggestion]):
    ids = {s.entity_id for s in _all_stacks(state)}
    long_soon = next((e for e in ids if e.endswith("_r_d")), None)
    rival = next((e for e in ids if e.endswith("_r_c")), None)
    if long_soon:
        out.append(Suggestion(165,
            tr(f"「{display_name(long_soon)}」即将飞升！",
               f"{display_name(long_soon)} is about to ascend!"),
            tr("对手先你一步就是败北结局。抢先完成飞升，或立刻用刃系手下暗杀（等级 10+ 必成，5-9 约七成）。",
               "If the rival ascends first, you lose. Race your own ascension, or send an Edge "
               "follower to kill them now (level 10+ always works, 5-9 about 70%)."),
            urgent=True))
    elif rival:
        out.append(Suggestion(90,
            tr(f"对手「{display_name(rival)}」已成气候",
               f"Rival {display_name(rival)} is gathering strength"),
            tr("长生者候补会稳步推进自己的飞升。趁早处理：刃系手下暗杀，或加快自己的野心进度。",
               "A would-be Long advances steadily toward their own ascension. Deal with them "
               "early — an Edge follower's knife, or simply outpace them.")))


def _cult_rules(state: GameState, out: list[Suggestion]):
    ids = {s.entity_id for s in _all_stacks(state)}
    if any(e.startswith("cult") for e in ids):
        return
    has_acq = any(has_aspect(e, "acquaintance") for e in ids)
    has_lore = any(e.startswith("fragment") for e in ids)
    if has_acq and has_lore:
        out.append(Suggestion(75,
            tr("可以建立教团了", "You can found your cult"),
            tr("把熟人和一份秘传放入「交谈」即可解锁建团。教团的系别决定仪式与手下方向，灯之教派对新手最友好。",
               "Talk with an acquaintance plus a lore fragment to unlock founding. The lore's "
               "aspect sets your cult's leaning — Lantern is the most forgiving choice.")))


def _ascension_rules(state: GameState, out: list[Suggestion]):
    pos = _ascension_position(state)
    if not pos:
        return
    track, stage, eid = pos
    if track == "change":  # the Dancer's own road
        out.append(Suggestion(58,
            tr("蜕变之路进行中", "The road of Change continues"),
            tr("在夜总会跳舞（4 级心或蛾之影响 + 欲望卡）换取「课程」，逐步完成蜕变。",
               "Dance at the club (a level-4 Heart or Moth influence with your desire card) "
               "to earn the surrendering lessons, one by one.")))
        return
    lore = ASCENSION_LORE[track]
    lore_zh = {"forge": "铸", "lantern": "灯", "grail": "杯"}[lore]
    if stage == "a":
        out.append(Suggestion(68,
            tr(f"野心 1→2：入梦 =「{display_name(eid)}」+ {lore_zh}之秘传",
               f"Ambition 1→2: dream the {display_name(eid)} with {lore.capitalize()} lore"),
            tr("升级为奉献后路线基本定型，确认方向再投入。",
               "Dedication all but locks the route — be sure before you commit.")))
    elif stage == "b":
        levels = _lore_levels(state)
        has_way = any(s.entity_id == "waystag_after" for s in _all_stacks(state))
        has_lore6 = levels.get(lore, 0) >= 6
        if has_way and has_lore6:
            out.append(Suggestion(85,
                tr(f"野心 2→3 条件已齐：工作 = 奉献 + 牡鹿之门道路 + 6 级{lore_zh}之秘传",
                   f"Ambition 2→3 is ready: work the Dedication + Way: Stag Door + level-6 {lore} lore"),
                tr("升到 3 级后路线锁定，此后只能在野心时节继续升级。",
                   "Level 3 locks the route; further levels come only in Ambition seasons.")))
        else:
            missing = []
            if not has_way:
                missing.append(tr("「牡鹿之门道路」（漫宿答谜获得）",
                                  "Way: Stag Door (answer the riddle in the Mansus)"))
            if not has_lore6:
                missing.append(tr(f"6 级{lore_zh}之秘传（同类 ×2 + 理性合成升级）",
                                  f"level-6 {lore} lore (combine pairs with Reason)"))
            out.append(Suggestion(62,
                tr("野心 2→3 还缺：" + "、".join(missing),
                   "Ambition 2→3 still needs: " + "; ".join(missing)),
                ""))
    elif stage in "cde":
        level = "abcdef".index(stage) + 1
        zh_t, en_t = TRIBUTE[track]
        out.append(Suggestion(60,
            tr(f"野心已 {level} 级：等待野心时节升级",
               f"Ambition at {level}: wait for an Ambitions season"),
            tr(f"时节会吸走欲望卡考验升级，需献上{zh_t}；备不齐会产生躁动。",
               f"The season devours the desire card and demands {en_t}; "
               "failing the test breeds Restlessness.")))
    elif stage == "f":
        out.append(Suggestion(70,
            tr("欲望已达 6 级——终局在望", "Desire at 6 — the endgame is in sight"),
            tr("集齐主系秘传（合计 36+）、准备高级影响与仪式即可飞升；先见者的援手能更进一步。",
               "Amass 36+ total in your prime lore, ready a high influence and the rite, "
               "and ascend; a Know-hand ally raises the victory tier.")))


def _mansus_expedition_rules(state: GameState, out: list[Suggestion]):
    ids = {s.entity_id for s in _all_stacks(state)}
    if any(e.startswith("waystagbefore") for e in ids):
        out.append(Suggestion(66,
            tr("牡鹿之门谜语待解", "The Stag Door's riddle awaits"),
            tr("在漫宿出示谜面对应的 6 级秘传即可通过，获得「牡鹿之门道路」（野心 3 级必需）。",
               "Present the level-6 lore the riddle names to pass and earn Way: Stag Door "
               "(required for Ambition 3).")))
    vault = next((e for e in ids if e.startswith("vault.")), None)
    if vault:
        out.append(Suggestion(64,
            tr(f"藏宝地「{display_name(vault)}」待远征",
               f"Expedition available: {display_name(vault)}"),
            tr("先派 1 名雇员 + 1 资金侦察，看清全部障碍再上主力（蛾克环境、启/铸克封印、刃克守卫、心/灯克诅咒）。远征结束必得 1 邪名，提前想好善后。",
               "Scout first with one hireling + 1 Funds to reveal every obstacle (Moth beats "
               "terrain, Knock/Forge seals, Edge guardians, Heart/Lantern curses). Every "
               "expedition ends with 1 Notoriety — plan the cleanup.")))


def _progression_rules(state: GameState, out: list[Suggestion]):
    if (state.active_legacy or "").startswith("exile"):
        return  # the Exile has none of these systems
    _rival_rules(state, out)
    _cult_rules(state, out)
    _ascension_rules(state, out)
    _mansus_expedition_rules(state, out)


def _ghoul_rules(state: GameState, out: list[Suggestion]):
    qty = lambda eid: stack_quantity(state, eid)

    if qty("ghouljob.first") or qty("ghouljob"):
        out.append(Suggestion(110,
                              tr(f"把「{display_name('ghouljob')}」放入「{display_name('work')}」",
                                 f"Put {display_name('ghouljob')} into {display_name('work')}"),
                              tr("推进主线并获得报酬。", "Advances the story and pays.")))

    if qty("erudition") == 1:
        out.append(Suggestion(60,
                              tr(f"「{display_name('erudition')}」在场，可趁消失前研读",
                                 f"{display_name('erudition')} on table — study before it fades"),
                              ""))

    funds = qty("funds")
    if qty("health") > 0 and funds < 2:
        out.append(Suggestion(100,
                              tr(f"用「{display_name('health')}」去「{display_name('work')}」赚钱",
                                 f"Work {display_name('health')} for Funds"),
                              tr(f"当前资金 {funds}。", f"Funds: {funds}."),
                              urgent=funds == 0))
    if funds > 0:
        out.append(Suggestion(40,
                              tr(f"有闲置资金，可以「{display_name('explore')}」",
                                 f"Spare Funds — consider {display_name('explore')}"),
                              tr(f"当前资金 {funds}。", f"Funds: {funds}.")))


def _aspirant_rules(state: GameState, out: list[Suggestion]):
    for eid in ("job", "menial-employment", "menial"):
        if stack_quantity(state, eid):
            out.append(Suggestion(100,
                                  tr(f"把「{display_name(eid)}」放入「{display_name('work')}」",
                                     f"Put {display_name(eid)} into {display_name('work')}"),
                                  tr("维持收入。", "Keeps the income flowing.")))
            break


LEGACY_RULES = {
    "ghoul": _ghoul_rules,
    "aspirant": _aspirant_rules,
}


def advise(state: GameState) -> Advice:
    advice = Advice(
        character=state.character_name,
        legacy=state.active_legacy,
        resources=_resources(state),
        verbs=_verbs(state),
    )
    running = [v for v in advice.verbs if v.time_remaining > 0 and v.verb_id != "time"]

    _generic_rules(state, advice.suggestions)
    _opening_rules(state, advice.suggestions)
    _progression_rules(state, advice.suggestions)
    rules = LEGACY_RULES.get(state.active_legacy)
    if rules:
        rules(state, advice.suggestions)

    if not advice.suggestions and running:
        advice.suggestions.append(Suggestion(0, tr("等待中", "Waiting"),
                                             tr("所有行动都在进行，暂时无事可做。",
                                                "Everything is in motion; nothing to do right now.")))

    advice.suggestions.sort(key=lambda s: -s.priority)
    return advice
