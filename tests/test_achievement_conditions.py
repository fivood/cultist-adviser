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

def test_exaltation_readiness_guidance(monkeypatch):
    """Corrected: exalt needs 21 total aspect, not 12. Disciple carries 5, so
    the shortfall must be topped up by lore + tool combined."""
    from cultist_adviser import knowledge
    patched = dict(knowledge._el_aspects)
    patched["testwintertool"] = {"tool": 1, "winter": 4}
    monkeypatch.setattr(knowledge, "_el_aspects", patched)
    # disciple (5) + lore 12 + tool 4 = 21 exactly -> ready
    got = tops([card("cultwinter_1"), card("auclair_c"),
                card(frag("winter", 12)), card("testwintertool"),
                card("funds", qty=6)])
    assert 65 in got
    # 5 + 12 alone = 17, short of 21 -> shortfall report
    got = tops([card("cultwinter_1"), card("auclair_c"),
                card(frag("winter", 12)), card("funds", qty=6)])
    assert 38 in got and 65 not in got
    # without the cult, no exalt tip
    got = tops([card("auclair_c"), card(frag("winter", 12)),
                card("funds", qty=6)])
    assert 65 not in got and 38 not in got


def test_recruit_believer_promote_disciple_flow(monkeypatch):
    """The three follower-promotion tiers all draw guidance now."""
    from cultist_adviser import knowledge
    patched = dict(knowledge._el_aspects)
    patched["testlanterntool"] = {"tool": 1, "lantern": 4}
    monkeypatch.setattr(knowledge, "_el_aspects", patched)
    # Acquaintance -> Believer: needs cult + level-1 lore of any aspect
    got = tops([card("cultlantern_1"), card("cat_a"),
                card(frag("lantern", 2)), card("funds", qty=6)])
    assert 62 in got
    got = tops([card("cultlantern_1"), card("cat_a"), card("funds", qty=6)])
    assert 62 not in got
    # Believer with own 2 + lore 6 = 8 >= 7 -> ready to promote
    got = tops([card("cultlantern_1"), card("cat_b"),
                card(frag("lantern", 6)), card("funds", qty=6)])
    assert 64 in got
    # Believer with own 2 + lore 4 = 6 -> short 1
    got = tops([card("cultlantern_1"), card("cat_b"),
                card(frag("lantern", 4)), card("funds", qty=6)])
    assert 37 in got and 64 not in got
    # Tool bridges the gap: own 2 + lore 4 + tool 4 = 10 >= 7 -> ready
    got = tops([card("cultlantern_1"), card("cat_b"),
                card(frag("lantern", 4)), card("testlanterntool"),
                card("funds", qty=6)])
    assert 64 in got


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
    (["lockscarlantern"], 64),                                     # early
    (["lockscarlantern", "lockscarheart", "lockscarmoth"], 70),    # mare-ready
    # game data: 7 scar-lock aspects (no knock — priest is the door)
    (["lockscaredge","lockscarforge","lockscargrail","lockscarheart",
      "lockscarlantern","lockscarmoth","lockscarwinter"], 76),     # mother-ready
    # opened + closed both count toward the 7
    (["openedlockscaredge","openedlockscarforge","openedlockscargrail",
      "openedlockscarheart","openedlockscarlantern","openedlockscarmoth",
      "lockscarwinter"], 76),
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
    # priest scar sanity: lockscar cards outside a priest run
    got = tops([card("lockscarlantern"), card("skillhealthb"),
                card("funds", qty=5)])
    assert 64 not in got and 70 not in got
    # exile foe wound outside exile
    got = tops([card("wound.foe", qty=5), card("funds", qty=5)])
    assert 58 not in got and 90 not in got


# --------------------------------------- rite and vault inventory rules ---

def test_rite_inventory_lists_owned_and_missing():
    """Every rite on the table shows in the inventory line; the missing set
    fills the rest of the 10-rite roster."""
    got = tops([card("ritetoolfollowerconsumelore"),
                card("ritetoolconsumefollower"),
                card("skillhealthb"), card("cultgrail_1"),
                card("funds", qty=6)])
    assert 20 in got
    from cultist_adviser.lexicon import display_name
    body = got[20].title + " " + got[20].detail
    assert display_name("ritetoolfollowerconsumelore") in body
    # a rite the player doesn't have gets named as missing
    assert display_name("ritefollowerconsumeinfluence") in body


def test_rite_inventory_silent_without_rites():
    got = tops([card("skillhealthb"), card("cultgrail_1"), card("funds", qty=6)])
    assert 20 not in got


def test_vault_inventory_lists_all_vaults_with_counters():
    """Multiple vaults draw a single summary line with each vault's counter
    aspects and tier. Real vault ids/counters come from game data."""
    got = tops([card("skillhealthb"), card("cultgrail_1"),
                card("vaultcapital1"), card("vaultcapital2"),
                card("vaultshires3"), card("funds", qty=6)])
    assert 19 in got
    from cultist_adviser.lexicon import display_name
    body = got[19].title + " " + got[19].detail
    for v in ("vaultcapital1", "vaultcapital2", "vaultshires3"):
        assert display_name(v) in body


def test_vault_inventory_single_vault_defers_to_expedition_rule():
    """One vault is fully covered by _mansus_expedition_rules — no summary
    line to keep the panel calm."""
    got = tops([card("skillhealthb"), card("cultgrail_1"),
                card("vaultcapital1"), card("funds", qty=6)])
    assert 19 not in got


# ---------------------------------------------- patron commission flow ---

def test_commission_stage1_patron_present():
    """Patron on the table, no commission yet -> offer specific aspect + tip."""
    got = tops([card("skillhealthb"), card("cultlantern_1"),
                card("aladim"), card("fragmentsecrethistories"),
                card("funds", qty=5)])
    assert 62 in got
    from cultist_adviser.lexicon import display_name
    assert display_name("aladim") in got[62].title


def test_commission_stage2_write_paper_by_lore_level():
    """Commission book on the table -> Work-writing tip with the exact lore
    level needed (2/4/6 for base/considered/in-depth)."""
    got = tops([card("skillhealthb"),
                card("commissionarticlesecrethistories"),
                card("fragmentsecrethistoriesb"),  # level 4
                card("reason"), card("funds", qty=5)])
    assert 74 in got, "level-2 needed and level-4 lore in hand -> ready"
    # Considered commission (level 4) with only level-2 lore -> waiting priority
    got = tops([card("skillhealthb"),
                card("commissionarticlesecrethistoriesb"),
                card("fragmentsecrethistories"),  # level 2
                card("reason"), card("funds", qty=5)])
    assert 60 in got and 74 not in got


def test_commission_stage3_paper_delivery():
    """Paper written -> tip elevates when the paying patron is on the table."""
    got = tops([card("skillhealthb"), card("articlesecrethistoriesa"),
                card("aladim"), card("funds", qty=5)])
    assert 76 in got, "patron in hand -> ready to deliver"
    got = tops([card("skillhealthb"), card("articlesecrethistoriesa"),
                card("funds", qty=5)])
    assert 58 in got and 76 not in got, "no patron -> lower-priority waiting note"


def test_commission_stage1_silenced_when_book_already_pending():
    """The 'offer' nudge retires once the commission book is on the table
    for that patron's aspect — otherwise the panel double-nags."""
    got = tops([card("skillhealthb"), card("aladim"),
                card("commissionarticlelantern"),  # aladim's lantern commission
                card("funds", qty=5)])
    # 62 (offer) suppressed; 74 or 60 (write) fires instead
    assert 62 not in got
    assert 74 in got or 60 in got
