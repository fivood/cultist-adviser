"""Rule-engine tests on synthetic game states.

No game installation required: names fall back to raw ids when the lexicon is
empty, and the aspect table is injected per-test. Assertions key off suggestion
priorities and urgency, which are stable constants, never localized text.
"""
import pytest

from cultist_adviser.save_parser import GameState, ElementStack, Situation
from cultist_adviser import knowledge
from cultist_adviser.advisor import advise

TABLETOP = "~/tabletop"
_n = 0


def card(eid, qty=1, lifetime=0.0, sphere=TABLETOP):
    global _n
    _n += 1
    return ElementStack(id=f"t{_n}", entity_id=eid, quantity=qty,
                        position=(0, 0, 0), sphere_path=sphere,
                        lifetime_remaining=lifetime)


def verb(vid, time_remaining=0.0, recipe=""):
    global _n
    _n += 1
    return Situation(id=f"v{_n}", entity_id=vid, quantity=1,
                     position=(0, 0, 0), sphere_path=TABLETOP,
                     verb_id=vid, recipe_id=recipe, time_remaining=time_remaining)


def state(tokens, legacy="aspirant", draw_piles=None):
    return GameState(character_name="T", profession="", active_legacy=legacy,
                     version="", tokens=list(tokens), draw_piles=draw_piles or {})


def suggestions(st):
    return advise(st).suggestions


def by_priority(st, priority):
    return [s for s in suggestions(st) if s.priority == priority]


@pytest.fixture(autouse=True)
def aspect_table(monkeypatch):
    """Minimal aspect index so tests run without the game's content files."""
    table = dict(knowledge._el_aspects)
    table.update({
        "auclair_a": {"acquaintance": 1},
        "auclair_b": {"follower": 1, "winter": 2},
        "auclair_c": {"follower": 1, "disciple": 1, "winter": 5},
        "auclair_p": {"prisoner": 1},
        "victor_c": {"follower": 1, "disciple": 1, "moth": 5},
        "slee_c": {"follower": 1, "disciple": 1, "edge": 5},
        "defaulthunter": {"hunter": 1, "mortal": 1},
        "evidence": {"evidencelevel": 1},
        "evidenceb": {"evidencelevel": 2},
        "vaultcapital1": {"vault": 1},
        "fakebooklatin": {"text": 1, "textlatin": 1},
        "fakebook": {"text": 1},
        "textbooklatin": {"text": 1},
        "fakefragment": {"lore": 1},
        "fakeinfluence": {"influence": 1},
        "fakeway": {"way": 1},
    })
    monkeypatch.setattr(knowledge, "_el_aspects", table)
    monkeypatch.setattr(knowledge, "_vaults",
                        {"vaultcapital1": ["guardian_watchers"]})
    monkeypatch.setattr(knowledge, "_counters",
                        {"guardian_watchers": ["grail", "moth", "edge"]})


# ------------------------------------------------------------- opening ---

def test_aspirant_first_move_and_banner():
    st = state([card("introjob"), verb("work"), verb("time", 55)])
    assert by_priority(st, 120), "first-move guide should fire"
    assert by_priority(st, 55), "opening banner should fire before any skill"


def test_opening_banner_retires_after_first_skill():
    st = state([card("introjob"), card("skillhealtha"), verb("work"), verb("time", 55)])
    assert not by_priority(st, 55)


def test_ghoul_seance_memory_menu():
    st = state([card("ghouljob.first"), card("memory.shameful"),
                verb("work"), verb("time", 55)], legacy="ghoul")
    assert by_priority(st, 115)


def test_exile_gets_disclaimer_and_no_funds_nag():
    st = state([card("ticket.train"), verb("use"), verb("time.exile", 55)],
               legacy="exile")
    subs = suggestions(st)
    assert any(s.priority == 12 for s in subs), "exile disclaimer"
    assert not any(s.priority in (90, 145) for s in subs), "funds rule must skip exile"


# ---------------------------------------------------------------- danger ---

def test_despair_countdown_alert():
    st = state([verb("despair", 30), verb("time", 55)])
    alerts = by_priority(st, 200)
    assert alerts and alerts[0].urgent


def test_spiral_warning_urgent_when_season_pending():
    piles = {"seasonevents_draw": ["seasondespair", "seasonsuspicion"]}
    st = state([card("dread", 2), verb("time", 55)], draw_piles=piles)
    alerts = by_priority(st, 160)
    assert alerts and alerts[0].urgent


def test_spiral_warning_softened_when_season_exhausted():
    piles = {"seasonevents_draw": ["seasonsuspicion", "seasonsickness"]}
    st = state([card("dread", 2), verb("time", 55)], draw_piles=piles)
    assert not by_priority(st, 160)
    softened = by_priority(st, 40)
    assert softened and not softened[0].urgent


def test_spiral_warning_conservative_without_pile_data():
    st = state([card("dread", 2), verb("time", 55)])  # no draw_piles at all
    assert by_priority(st, 160)


# ----------------------------------------------------------- season deck ---

def test_season_deck_listing_and_reshuffle_notice():
    piles = {"seasonevents_draw": ["seasonsickness", "seasonambitions"]}
    assert by_priority(state([verb("time", 55)], draw_piles=piles), 14)
    empty = {"seasonevents_draw": []}
    assert by_priority(state([verb("time", 55)], draw_piles=empty), 14)


# ------------------------------------------------------------------ doom ---

def test_trial_alert_fires_on_trial_recipes_only():
    trial = state([verb("suspicion", 25, recipe="suspicionpretrial"), verb("time", 55)])
    assert by_priority(trial, 190) and by_priority(trial, 190)[0].urgent
    benign = state([verb("suspicion", 25, recipe="suspicioncreateevidence"),
                    verb("time", 55)])
    assert not by_priority(benign, 190)


def test_poppy_and_assassination_and_rival_rite():
    st = state([verb("poppytime", 280, recipe="poppytimebomb"), verb("time", 55)])
    assert by_priority(st, 175)
    st = state([verb("longassault.assassination", 100,
                     recipe="long.executestrategy.assassination.begin"),
                verb("time", 55)])
    assert by_priority(st, 185)
    st = state([verb("ambition", 60, recipe="L_ascension_rival"), verb("time", 55)])
    assert by_priority(st, 195)


def test_sickness_resolution_alert():
    st = state([verb("illhealth", 40, recipe="sickness"), verb("time", 55)])
    assert by_priority(st, 155)


# ----------------------------------------------------------- progression ---

def test_cult_founding_ready_and_suppressed():
    base = [card("acquaintance"), card("fragmentlantern"), card("skillhealtha"),
            verb("talk"), verb("time", 55)]
    assert by_priority(state(base), 75)
    assert not by_priority(state(base + [card("cultlantern_1")]), 75)


def test_cult_missing_piece_hints():
    acq_only = state([card("acquaintance"), card("skillhealtha"), verb("time", 55)])
    assert by_priority(acq_only, 58), "missing-lore hint"
    lore_only = state([card("fragmentlantern"), card("skillhealtha"), verb("time", 55)])
    assert by_priority(lore_only, 58), "missing-acquaintance hint"
    both = state([card("acquaintance"), card("fragmentlantern"),
                  card("skillhealtha"), verb("time", 55)])
    assert not by_priority(both, 58) and by_priority(both, 75)


def test_stage_banner_follows_progress():
    # Past the opening (skill present), no cult -> "found your cult" arc.
    no_cult = state([card("skillhealtha"), verb("time", 55)])
    assert by_priority(no_cult, 54)
    # Opening phase: covered by the opening banner instead.
    fresh = state([card("introjob"), verb("time", 55)])
    assert not by_priority(fresh, 54) and by_priority(fresh, 55)
    # Keeper level hides the banner (it's guidance).
    subs = advise(no_cult, spoiler=0).suggestions
    assert not any(s.priority == 54 for s in subs)


def test_endgame_checklist_counts_lore():
    common = [card("skillhealtha"), card("cultlantern_1"), verb("time", 55)]
    short = state(common + [card("ascensionenlightenmentf"), card("fragmentlanternc")])
    alerts = by_priority(short, 70)
    assert alerts and "6/36" in alerts[0].detail
    enough = state(common + [card("ascensionenlightenmentf"),
                             card("fragmentlanterng", 2), card("fragmentlanterne")])
    alerts = by_priority(enough, 70)
    assert alerts and "38/36" in alerts[0].detail


def test_ascension_b_missing_vs_ready():
    common = [card("skillhealtha"), card("cultlantern_1"), verb("time", 55)]
    missing = state(common + [card("ascensionenlightenmentb"), card("fragmentlantern")])
    assert by_priority(missing, 62) and not by_priority(missing, 85)
    ready = state(common + [card("ascensionenlightenmentb"),
                            card("fragmentlanternc"), card("waystag_after")])
    assert by_priority(ready, 85) and not by_priority(ready, 62)


def test_rival_cards():
    st = state([card("auclair_r_d"), card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(st, 165)
    assert alerts and alerts[0].urgent
    st = state([card("auclair_r_c"), card("skillhealtha"), verb("time", 55)])
    assert by_priority(st, 90)


def test_ambition_season_forecast_demands_tribute():
    st = state([card("ascensionenlightenmentc"), card("skillhealtha"),
                card("seasonambitions", sphere="~/tabletop/!time_1/slot"),
                verb("time", 40)])
    alerts = by_priority(st, 170)
    assert alerts and alerts[0].urgent
    # with a prisoner ready, the forecast is informational (priority 15)
    st = state([card("ascensionenlightenmentc"), card("skillhealtha"),
                card("auclair_p"),
                card("seasonambitions", sphere="~/tabletop/!time_1/slot"),
                verb("time", 40)])
    assert not by_priority(st, 170) and by_priority(st, 15)


def test_gentle_season_forecasts():
    st = state([card("skillhealtha"),
                card("seasonsilence", sphere="~/tabletop/!time_1/slot"),
                verb("time", 40)])
    forecasts = by_priority(st, 15)
    assert forecasts and forecasts[0].detail, "silence forecast carries the tip"
    keeper = [s for s in advise(st, spoiler=0).suggestions if s.priority == 15]
    assert keeper and not keeper[0].detail, "keeper sees the forecast, not the tactic"


def test_prisoner_source_hint():
    st = state([card("ascensionenlightenmentc"), card("skillhealtha"),
                card("cultlantern_1"), verb("time", 55)])
    alerts = by_priority(st, 60)
    assert alerts and ("囚徒来源" in alerts[0].detail or "Prisoners" in alerts[0].detail)
    with_prisoner = state([card("ascensionenlightenmentc"), card("skillhealtha"),
                           card("cultlantern_1"), card("auclair_p"), verb("time", 55)])
    alerts = by_priority(with_prisoner, 60)
    assert alerts and "囚徒来源" not in alerts[0].detail


def test_mansus_door_check():
    # Holds waywood + a lantern-4 lore -> White Door reachable (priority 63).
    ready = state([card("waywood"), card("fragmentlanternb"),
                   card("skillhealtha"), verb("time", 55)])
    assert by_priority(ready, 63) and not by_priority(ready, 61)
    # Holds waywood but only level-2 lore -> gap report (priority 61).
    short = state([card("waywood"), card("fragmentlantern"),
                   card("skillhealtha"), verb("time", 55)])
    assert by_priority(short, 61) and not by_priority(short, 63)
    # All doors open -> silence.
    all_open = state([card("waywood"), card("waywhite"), card("wayspider"),
                      card("waypeacock"), card("skillhealtha"), verb("time", 55)])
    assert not by_priority(all_open, 61) and not by_priority(all_open, 63)


def test_stag_riddle_names_the_answer(english):
    held = state([card("waystagbefore_2"), card("fragmentlanternc"),
                  card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(held, 66)
    assert alerts and "present it" in alerts[0].detail
    missing = state([card("waystagbefore_2"), card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(missing, 66)
    assert alerts and "not yet" in alerts[0].detail


def test_long_scheming_counterplay():
    st = state([card("skillhealtha"), verb("long", 50, recipe="long.cycle"),
                verb("time", 55)])
    assert by_priority(st, 88)
    dueling = state([card("skillhealtha"),
                     verb("long", 25, recipe="long.assault.confrontation"),
                     verb("time", 55)])
    assert not by_priority(dueling, 88), "confrontation is the doom rule's job"


def test_progression_skipped_for_exile():
    st = state([card("acquaintance"), card("fragmentlantern"),
                verb("time.exile", 55)], legacy="exile")
    assert not by_priority(st, 75)


# -------------------------------------------------------------- dispatch ---

@pytest.fixture
def english():
    from cultist_adviser import lexicon
    lexicon.set_language("en")
    yield
    lexicon.set_language("zh")


def test_evidence_tip_scales_with_moth_follower(english):
    with_moth = state([card("evidence", 1, 200), card("victor_c"),
                       card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(with_moth, 125)
    assert alerts and "70" in alerts[0].detail
    without = state([card("evidence", 1, 200), card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(without, 125)
    assert alerts and "70" not in alerts[0].detail


def test_hunter_alert_with_and_without_muscle(english):
    armed = state([card("defaulthunter"), card("slee_c"),
                   card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(armed, 120)
    assert alerts and alerts[0].urgent and "70" in alerts[0].detail
    unarmed = state([card("defaulthunter"), card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(unarmed, 120)
    assert alerts and "10" in alerts[0].detail


# ------------------------------------------------- books / lore / vaults ---

def test_unreadable_book_flagged_until_scholar(english):
    base = [card("fakebooklatin"), card("skillhealtha"), verb("time", 55)]
    assert by_priority(state(base), 72)
    assert not by_priority(state(base + [card("scholarlatin")]), 72)


def test_bookshop_stock_info():
    piles = {"commontomes_draw": ["textbooklatin", "fakebook"]}
    assert by_priority(state([verb("time", 55)], draw_piles=piles), 13)
    assert by_priority(state([verb("time", 55)],
                             draw_piles={"commontomes_draw": []}), 13)


def test_lore6_plan_branches(english):
    from cultist_adviser.advisor import _lore6_plan
    combine = state([card("fragmentlanternb"), card("fragmentlantern"), verb("time", 55)])
    assert "combine" in _lore6_plan(combine, "lantern", "灯")
    subvert = state([card("fragmentlanternb"), card("fragmentmoth"), verb("time", 55)])
    assert "subvert" in _lore6_plan(subvert, "lantern", "灯")
    empty = state([verb("time", 55)])
    assert "Gather" in _lore6_plan(empty, "lantern", "灯")


def test_expedition_battle_plan_rates_followers(english):
    armed = state([card("vaultcapital1"), card("slee_c"),
                   card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(armed, 64)
    assert alerts and "70" in alerts[0].detail  # Edge-5 vs the watchers
    unarmed = state([card("vaultcapital1"), card("skillhealtha"), verb("time", 55)])
    alerts = by_priority(unarmed, 64)
    assert alerts and "fail" in alerts[0].detail


# ---------------------------------------------------------- spoiler tiers ---

def test_keeper_hides_guidance_but_keeps_survival():
    from cultist_adviser.advisor import advise as adv
    st = state([card("introjob"), card("dread", 2), verb("work"), verb("time", 55)])
    keeper = adv(st, spoiler=0).suggestions
    assert not any(s.priority == 120 for s in keeper), "opening guide hidden"
    assert any(s.priority == 160 for s in keeper), "spiral warning stays"
    assert any(s.priority == 5 for s in keeper), "hidden-hints note shown"
    full = adv(st, spoiler=2).suggestions
    assert any(s.priority == 120 for s in full)
    assert not any(s.priority == 5 for s in full)


def test_bequest_choice_softened_below_full_spoiler():
    from cultist_adviser.advisor import advise as adv
    st = state([card("bequestintro"), card("reason"), verb("study"), verb("time", 55)])
    soft = next(s for s in adv(st, spoiler=1).suggestions if s.priority == 115)
    full = next(s for s in adv(st, spoiler=2).suggestions if s.priority == 115)
    assert soft.detail != full.detail


def test_season_deck_names_only_at_full_spoiler():
    from cultist_adviser.advisor import advise as adv
    piles = {"seasonevents_draw": ["seasonsickness", "seasonambitions"]}
    st = state([verb("time", 55)], draw_piles=piles)
    guide = next(s for s in adv(st, spoiler=1).suggestions if s.priority == 14)
    assert "×" not in guide.detail and "1×" not in guide.detail
    keeper = adv(st, spoiler=0).suggestions
    assert not any(s.priority == 14 for s in keeper)


def test_expedition_plan_needs_scouting_at_guide_level(english):
    from cultist_adviser.advisor import advise as adv
    unscouted = state([card("vaultcapital1"), card("slee_c"),
                       card("skillhealtha"), verb("time", 55)])
    hint = next(s for s in adv(unscouted, spoiler=1).suggestions if s.priority == 64)
    assert "Scout" in hint.detail
    scouted = state([card("vaultcapital1"), card("guardian_watchers"),
                     card("slee_c"), card("skillhealtha"), verb("time", 55)])
    plan = next(s for s in adv(scouted, spoiler=1).suggestions if s.priority == 64)
    assert "70" in plan.detail


# --------------------------------------------------------------- cooldowns ---

def test_cooldown_detection():
    from cultist_adviser.advisor import is_cooldown
    assert is_cooldown("fatigue")
    assert is_cooldown("passionexhausted")
    assert is_cooldown("weapon.a.exhausted")
    assert is_cooldown("contact.barber.fatigued")
    assert not is_cooldown("dread")
    assert not is_cooldown("health")
    assert not is_cooldown("fascination")


def test_cooldowns_dont_trigger_expiring_nag():
    st = state([card("fatigue", 1, 40), card("passionexhausted", 1, 30),
                card("skillhealtha"), verb("time", 55)])
    subs = advise(st).suggestions
    # Priority 80 and 150 are the expiring nags; neither should fire for cooldowns.
    assert not any(s.priority in (80, 150) and (
        "疲" in s.title or "Fatigue" in s.title or "Exhausted" in s.title)
        for s in subs)


# ------------------------------------------------------------- gui logic ---

def test_resource_categorization():
    pytest.importorskip("tkinter")
    from cultist_adviser.gui import _categorize
    assert _categorize("dread") == "threats"
    assert _categorize("defaulthunter") == "threats"
    assert _categorize("funds") == "core"
    assert _categorize("fatigue") == "core"
    assert _categorize("fakefragment") == "lore"
    assert _categorize("fakebooklatin") == "books"
    assert _categorize("auclair_b") == "people"
    assert _categorize("vaultcapital1") == "places"
    assert _categorize("fakeway") == "places"
    assert _categorize("fakeinfluence") == "influence"
    assert _categorize("mysteriousthing") == "misc"


def test_use_ways_and_aspect_fallback():
    """The double-click dialog's 'uses' tab: direct id match plus an aspect
    fallback for follower/acquaintance-style cards."""
    from cultist_adviser.knowledge import use_ways
    # A recipe consumes 'fakekey' directly.
    from cultist_adviser import knowledge as km
    recipes = [
        {"id": "r1", "action": "work", "craftable": True,
         "req": {"fakekey": 1, "reason": 1}, "eff": {"funds": 1}},
        {"id": "r2", "action": "talk", "craftable": True,
         "req": {"fakeaspect": 1, "dread": 1}, "eff": {"contentment": 1}},
    ]
    obtain = {}
    uses = {}
    for i, r in enumerate(recipes):
        for k in r["req"]:
            uses.setdefault(k, []).append(i)
    aspects = {"fakekey": {}, "fakepivot": {"fakeaspect": 1}}
    orig = km._recipes, km._uses, km._el_aspects
    km._recipes, km._uses, km._el_aspects = recipes, uses, aspects
    try:
        direct = use_ways("fakekey")
        assert direct and "work" in direct[0].lower() or "作业" in direct[0]
        via_aspect = use_ways("fakepivot")
        assert via_aspect, "aspect fallback should surface the recipe"
        empty = use_ways("nothing")
        assert empty == []
    finally:
        km._recipes, km._uses, km._el_aspects = orig


def test_pause_detection_logic():
    tk = pytest.importorskip("tkinter")  # noqa: F841 — gui imports tkinter
    import time
    from cultist_adviser import gui

    class Fake:
        parsed_at = 0.0
        save_deadline = 0.0
        _likely_paused = gui.AdvisorApp._likely_paused
        _elapsed = gui.AdvisorApp._elapsed

    f = Fake()
    now = time.time()
    f.parsed_at, f.save_deadline = now - 10, 40.0
    assert not f._likely_paused() and 9 < f._elapsed() < 11
    f.parsed_at = now - 50  # deadline (40) + slack (5) blown
    assert f._likely_paused() and f._elapsed() == 0.0
    f.parsed_at, f.save_deadline = now - 300, 0.0  # no running verbs: no signal
    assert not f._likely_paused()
