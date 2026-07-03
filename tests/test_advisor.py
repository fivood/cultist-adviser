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
    })
    monkeypatch.setattr(knowledge, "_el_aspects", table)


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


def test_progression_skipped_for_exile():
    st = state([card("acquaintance"), card("fragmentlantern"),
                verb("time.exile", 55)], legacy="exile")
    assert not by_priority(st, 75)


# ------------------------------------------------------------- gui logic ---

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
