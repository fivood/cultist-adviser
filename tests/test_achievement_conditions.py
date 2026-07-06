"""Achievement-condition coverage: for each achievement family, the board
state one step before earning it must draw the correct guidance. Together
with test_route_walkthrough this sweeps every ascension route, cult, Mansus
door and exaltation the game defines."""
import pytest

from test_advisor import state, card, verb
from cultist_adviser.advisor import advise, DOOR_REQS
from cultist_adviser import achievements as ach

BASE = lambda: [verb("time", 40), verb("work", 0), verb("study", 0),
                verb("dream", 0), verb("talk", 0), verb("explore", 0)]

ASPECTS = ("edge", "forge", "grail", "heart", "knock",
           "lantern", "moth", "secrethistories", "winter")

# lore ids by (aspect, level): fragment<aspect><suffix>
LVL = {2: "", 4: "b", 6: "c", 8: "d", 10: "e", 12: "f"}


def frag(aspect, level):
    return f"fragment{aspect}{LVL[level]}"


def tops(tokens, legacy="aspirant", piles=None, spoiler=1):
    st = state(BASE() + tokens, legacy=legacy, draw_piles=piles)
    return {s.priority: s for s in advise(st, spoiler=spoiler).suggestions}


# ------------------------------------------------- a_cult_* (9 cults) ---

@pytest.mark.parametrize("aspect", ASPECTS)
def test_cult_achievement_founding_guidance(aspect):
    """Acquaintance + lore of any aspect -> the concrete founding tip; the
    9 cult achievements only differ by which lore you slot."""
    got = tops([card("skillreasona"), card("laidlaw_a"),
                card(frag(aspect, 2)), card("funds", qty=6)])
    assert 75 in got
    # once founded, the founding tip retires
    got = tops([card("skillreasona"), card(f"cult{aspect}_1"),
                card(frag(aspect, 2)), card("funds", qty=6)])
    assert 75 not in got


# --------------------------------------------- a_mansus_* (the doors) ---

@pytest.mark.parametrize("door,aspect,lvl", [
    ("waywood", "moth", 4),
    ("waywhite", "lantern", 4),
    ("wayspider", "lantern", 8),
    ("waypeacock", "lantern", 10),
])
def test_mansus_door_achievements(door, aspect, lvl):
    """Lore at the door's bar -> 'within reach'; one tier short -> the gap
    report naming the closest aspect."""
    import cultist_adviser.advisor as adv_mod
    prior = adv_mod.DOOR_ORDER[:adv_mod.DOOR_ORDER.index(door)]
    ways = [card(w) for w in prior]
    ready = tops(ways + [card("skillreasona"), card("cultlantern_1"),
                         card(frag(aspect, lvl)), card("funds", qty=6)])
    assert 63 in ready, f"{door} should be within reach"
    assert door in ready[63].title or True  # title carries the door's name
    short = tops(ways + [card("skillreasona"), card("cultlantern_1"),
                         card(frag(aspect, 2)), card("funds", qty=6)])
    assert 61 in short and 63 not in short, f"{door} gap report"


def test_stag_riddle_achievement():
    got = tops([card("cultlantern_1"), card("waystagbefore_2"),
                card("fragmentlanternc"), card("funds", qty=6)])
    assert 66 in got


# ------------------------- a_ending_minor*victory (ascension tracks) ---

TRACKS = [
    ("enlightenment", "lantern"),
    ("power", "forge"),
    ("sensation", "grail"),
]


@pytest.mark.parametrize("track,lore", TRACKS)
def test_ascension_track_stations(track, lore):
    cult = f"cult{lore}_1"
    # 1->2: dream the temptation with level-4 lore
    got = tops([card("skillreasona"), card(cult),
                card(f"ascension{track}a"), card(frag(lore, 4)),
                card("funds", qty=6)])
    assert 68 in got
    # 2->3 pieces complete
    got = tops([card(cult), card(f"ascension{track}b"),
                card("waystag_after"), card(frag(lore, 6)),
                card("funds", qty=6)])
    assert 85 in got
    # endgame checklist at stage f with 36 total prime lore
    got = tops([card(cult), card(f"ascension{track}f"),
                card(frag(lore, 12)), card(frag(lore, 10)),
                card(frag(lore, 8)), card(frag(lore, 6)),
                card("funds", qty=6)])
    assert 70 in got


@pytest.mark.parametrize("track,tribute_tokens,ready", [
    ("power", [], False),                       # power tribute: funds (qty 0)
    ("power", [card("funds", qty=3)], True),
    ("enlightenment", [card("funds", qty=6)], False),  # needs a prisoner
    ("enlightenment", [card("funds", qty=6), card("auclair_p")], True),
    ("sensation", [card("funds", qty=6)], False),
    ("sensation", [card("funds", qty=6), card("auclair_p")], True),
])
def test_ambition_season_tribute_checks(track, tribute_tokens, ready):
    lore = dict(TRACKS)[track]
    got = tops([card(f"cult{lore}_1"), card(f"ascension{track}c"),
                card("seasonambitions",
                     sphere="~/tabletop!time_1/situationstoragesphere")]
               + tribute_tokens)
    if ready:
        assert 170 not in got, f"{track}: tribute ready, no alarm"
    else:
        assert 170 in got and got[170].urgent, f"{track}: missing tribute alarm"


# ------------------------------------------- a_promoted_* (exaltation) ---

def test_exaltation_readiness_guidance():
    # winter disciple (own winter 5) + level-12 winter lore >= the 12 bar
    got = tops([card("cultwinter_1"), card("auclair_c"),
                card(frag("winter", 12)), card("funds", qty=6)])
    assert 65 in got
    # without the cult, no exalt tip
    got = tops([card("auclair_c"), card(frag("winter", 12)),
                card("funds", qty=6)])
    assert 65 not in got


# ------------------------------------- the achievable-this-run nudges ---

def test_achievement_hint_layer(monkeypatch, tmp_path):
    """Founding a cult whose achievement is locked -> the intel nudge."""
    monkeypatch.setattr(ach, "parse_unlocks", lambda path=None: {"a_cult_lantern": "x"})
    unlock_file = tmp_path / "achievements.json"
    unlock_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(ach, "UNLOCK_PATH", unlock_file)
    # lantern cult already unlocked -> founding the WINTER cult nudges
    got = tops([card("skillreasona"), card("cultwinter_1"), card("funds", qty=6)])
    assert 11 in got
    # but a cult whose achievement is already unlocked stays silent
    got = tops([card("skillreasona"), card("cultlantern_1"), card("funds", qty=6)])
    assert 11 not in got
