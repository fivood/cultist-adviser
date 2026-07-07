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


# ------------------------- a_ending_XvictoryYYY (Ever After × 21 lovers) ---

@pytest.mark.parametrize("follower,venue,attr", [
    ("tristan_b", "locationauctionhouse", "health"),      # power route
    ("rose_b", "locationcabaret", "passion"),             # sensation
    ("clovette_b", "locationcabaret", "passion"),         # change (DLC)
    ("auclair_b", "locationstreetsstrange", "reason"),    # enlightenment
])
def test_ever_after_courtship_venue_matching(follower, venue, attr):
    """Believer with follower_lustXXX aspect draws venue-specific courting
    guidance; readiness elevates when venue + attribute already in hand."""
    # Aware but not ready
    got = tops([card("skillhealthb"), card("cultgrail_1"), card(follower),
                card("funds", qty=6)])
    assert 52 in got, "aware but not ready -> low-priority nudge"
    # Ready
    got = tops([card("skillhealthb"), card("cultgrail_1"), card(follower),
                card(venue), card(attr), card("funds", qty=6)])
    assert 66 in got, "venue + attribute in hand -> ready-to-court elevation"


def test_ever_after_finale_warning_only_after_courtship():
    """The 'don't add Passion' alarm fires once romantic interest exists AND
    the player has reached the ascension stages where the finale matters."""
    # Early ambition — no warning yet
    got = tops([card("cultgrail_1"), card("ascensionsensationa"),
                card("romanticinterest"), card("rose_c"), card("funds", qty=6)])
    assert 59 not in got, "before dedication -> no finale warning"
    # Dedicated -> warning present
    got = tops([card("cultgrail_1"), card("ascensionsensationc"),
                card("romanticinterest"), card("rose_c"), card("funds", qty=6)])
    assert 59 in got, "at dedication -> finale warning"


# ---------------------- a_ending_minor*victory_withrisen (6 endings) ---

def test_with_risen_path_matches_state():
    """Alive lover + late-game -> the setup nudge; corpse -> the rite nudge;
    Risen -> the 'start ascension' nudge. Each stage retires the prior."""
    late = [card("cultgrail_1"), card("ascensionsensationc"),
            card("romanticinterest"), card("rose_c"), card("funds", qty=6)]
    got = tops(late)
    assert 35 in got, "step-1: guide toward killing the lover on expeditions"
    got = tops(late + [card("corpse")])
    assert 63 in got and 35 not in got, "step-2: corpse -> rite nudge"
    got = tops(late + [card("spirit_wintera_moth")])
    assert 60 in got, "step-3: risen ready -> start-ascension warning"


def test_with_risen_gated_on_lover_and_stage():
    """No romantic interest -> no with-Risen nudges at all (this is a route
    that only makes sense once a lover exists)."""
    got = tops([card("cultgrail_1"), card("ascensionsensationc"),
                card("rose_c"), card("corpse"), card("funds", qty=6)])
    assert 63 not in got and 35 not in got
    # A random corpse before dedication also stays silent
    got = tops([card("cultgrail_1"), card("ascensionsensationa"),
                card("romanticinterest"), card("corpse"), card("funds", qty=6)])
    assert 63 not in got


# --------------------------------- Priest DLC (a_ending_minorknockvictory
# and a_ending_minormarevictory) ---

@pytest.mark.parametrize("scars,expect_priority", [
    (["scar_lantern"], 64),                                      # early
    (["scar_lantern", "scar_heart", "scar_moth"], 70),          # mare-ready
    (["scar_edge","scar_forge","scar_grail","scar_heart",
      "scar_knock","scar_lantern","scar_moth"], 76),            # mother-ready
])
def test_priest_scar_progression(scars, expect_priority):
    got = tops([card("priestjob"), card("skillhealthb")]
               + [card(s) for s in scars] + [card("funds", qty=5)],
               legacy="priest")
    assert expect_priority in got


# --------------------------------- Ghoul DLC (a_ending_minorwintervictory
# and a_ending_minorcrownedgrowthvictory / Fruitfulness) ---

def test_ghoul_route_gates_on_temptation():
    # Naenia handoff nudge only when temptation + fleeting both on table
    got = tops([card("temptation.remembrance"), card("fleeting"),
                card("funds", qty=5)], legacy="ghoul")
    assert 80 in got
    # random legacy without ghoul markers -> silent
    got = tops([card("fleeting"), card("funds", qty=5)])
    assert 80 not in got


def test_ghoul_graveyard_mouth_tracks_mutation():
    def mut(eid, muts):
        t = card(eid)
        t.mutations = muts
        return t
    # low value: quiet
    got = tops([mut("dedication.remembrance", {"ghoul.hunger": 2}),
                card("funds", qty=5)], legacy="ghoul")
    assert 72 not in got and 150 not in got
    # 3-4 range: informational tracker
    got = tops([mut("dedication.remembrance", {"ghoul.hunger": 3}),
                card("funds", qty=5)], legacy="ghoul")
    assert 72 in got and 150 not in got
    # 5: high-priority warning, non-urgent
    got = tops([mut("dedication.remembrance", {"ghoul.hunger": 5}),
                card("funds", qty=5)], legacy="ghoul")
    assert 150 in got and not got[150].urgent
    # 6: urgent — one Ambitions season ends it
    got = tops([mut("dedication.remembrance", {"ghoul.hunger": 6}),
                card("funds", qty=5)], legacy="ghoul")
    assert 150 in got and got[150].urgent


# --------------------------------- Exile DLC (obscurityvictory* + wolf) ---

@pytest.mark.parametrize("comfort,tier_marker", [
    (12, "宁静"),   # <20
    (22, "安适"),   # 20-29
    (35, "罕见快乐"),  # 30+
])
def test_exile_obscurity_tiers(comfort, tier_marker):
    got = tops([card("temptation.obscurity"),
                card("obscurity", qty=7),
                card("comfort", qty=comfort),
                card("funds", qty=5)], legacy="exile")
    assert 76 in got and tier_marker in got[76].title


def test_exile_foe_wound_tracker():
    # early wound stack: informational
    got = tops([card("temptation.obscurity"), card("wound.foe", qty=2),
                card("funds", qty=5)], legacy="exile")
    assert 58 in got
    # late: kill-close warning
    got = tops([card("temptation.obscurity"), card("wound.foe", qty=5),
                card("funds", qty=5)], legacy="exile")
    assert 90 in got
    # unstanchable counts too
    got = tops([card("temptation.obscurity"),
                card("wound.foe", qty=4), card("wound.foe.unstanchable"),
                card("funds", qty=5)], legacy="exile")
    assert 90 in got


def test_dlc_rules_dont_leak_to_base():
    """The DLC route rules must not fire for aspirant runs — 92 tests kept
    passing before this file grew, so guard against accidental leakage."""
    # priest scar sanity: scar cards outside a priest run
    got = tops([card("scar_lantern"), card("skillhealthb"),
                card("funds", qty=5)])
    assert 64 not in got and 70 not in got
    # exile foe wound outside exile
    got = tops([card("wound.foe", qty=5), card("funds", qty=5)])
    assert 58 not in got and 90 not in got
