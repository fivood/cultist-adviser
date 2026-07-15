"""End-to-end walkthrough regression: synthetic boards for each station of a
known winning route must draw the correct next-step guidance. Routes follow
the achievement guide (raw/成就.txt). Assertions key off priorities."""
from test_advisor import state, card, verb
from cultist_adviser.advisor import advise

BASE_VERBS = lambda: [verb("time", 40), verb("work", 0), verb("study", 0),
                      verb("dream", 0), verb("talk", 0), verb("explore", 0)]


def tops(tokens, legacy="aspirant", piles=None):
    st = state(BASE_VERBS() + tokens, legacy=legacy, draw_piles=piles)
    return {s.priority: s for s in advise(st, spoiler=1).suggestions}


def test_lantern_ascension_route():
    # A1 opening
    assert 120 in tops([card("introjob")])
    # A2 founding: acquaintance + lore -> concrete founding tip
    assert 75 in tops([card("skillreasona"), card("laidlaw_a"),
                       card("fragmentlantern"), card("funds", qty=6)])
    # A3 ambition 1->2: dream the temptation with lore
    got = tops([card("skillreasona"), card("cultlantern_1"),
                card("ascensionenlightenmenta"), card("fragmentlanternb"),
                card("funds", qty=6)])
    assert 68 in got and "1" in got[68].title
    # A4 dedication without the Way: gap report names what's missing
    got = tops([card("cultlantern_1"), card("ascensionenlightenmentb"),
                card("fragmentlanternb"), card("passion"), card("funds", qty=6)])
    assert 62 in got and 63 in got, "missing-way gap + open-the-Wood guidance"
    # A5 riddle in hand
    assert 66 in tops([card("cultlantern_1"), card("ascensionenlightenmentb"),
                       card("waystagbefore_2"), card("fragmentlanternc"),
                       card("funds", qty=6)])
    # A6 all pieces for ambition 2->3
    assert 85 in tops([card("cultlantern_1"), card("ascensionenlightenmentb"),
                       card("waystag_after"), card("fragmentlanternc"),
                       card("funds", qty=6)])
    # A7 Ambitions season next, no prisoner -> unprepared forecast fires
    got = tops([card("cultlantern_1"), card("ascensionenlightenmentc"),
                card("funds", qty=6),
                card("seasonambitions",
                     sphere="~/tabletop!time_1/situationstoragesphere")])
    assert 170 in got and got[170].urgent
    # A7b prisoner ready -> calm forecast
    got = tops([card("cultlantern_1"), card("ascensionenlightenmentc"),
                card("auclair_p"), card("funds", qty=6),
                card("seasonambitions",
                     sphere="~/tabletop!time_1/situationstoragesphere")])
    assert 170 not in got
    # A8 endgame: desire at 6, 36 total Lantern lore -> endgame checklist
    assert 70 in tops([card("cultlantern_1"), card("ascensionenlightenmentf"),
                       card("fragmentlanternf"), card("fragmentlanterne"),
                       card("fragmentlanternd"), card("fragmentlanternc"),
                       card("funds", qty=6)])


def test_dancer_change_route():
    # B1 the club contract is the trade
    got = tops([card("dancerjobecdysisa"), card("health", qty=2),
                card("funds", qty=5)], legacy="dancer")
    assert 72 in got
    # B2 temptation stage: exact 1->2 dance threshold
    got = tops([card("skillhealthb"), card("dancerjobecdysisa"),
                card("ascensionchangea"), card("health", qty=2),
                card("funds", qty=5)], legacy="dancer")
    assert 68 in got and "4" in got[68].title
    # B3+ leveled thresholds: stage b needs 6, stage f needs 15
    got = tops([card("skillhealthb"), card("ascensionchangeb"),
                card("funds", qty=5)], legacy="dancer")
    assert 58 in got and "6" in got[58].title
    got = tops([card("skillhealthb"), card("ascensionchangef"),
                card("funds", qty=5)], legacy="dancer")
    assert 58 in got and "15" in got[58].title
    # final dance at stage g
    got = tops([card("skillhealthb"), card("ascensionchangeg"),
                card("funds", qty=5)], legacy="dancer")
    assert 80 in got


def test_forge_apostle_route():
    # Dedicated opening restores the inherited organisation.
    assert 125 in tops([card("legacyapostleforgejob")], legacy="apostleforge")
    # A forged but dormant core points to the exact awakening material.
    got = tops([card("apostleforge.pillar1"),
                card("apostleforge.pillar2.dormant"),
                card("fragmentforgeg"), card("funds", qty=7)],
               legacy="apostleforge")
    assert 82 in got and "14" in got[82].detail
    assert 54 not in got, "ordinary ambition-stage banner must not leak into Apostle"


def test_grail_apostle_route_and_blood_deadline():
    assert 125 in tops([card("legacyapostlegrailjob")], legacy="apostlegrail")
    # Dormant blood is the route's immediate death threat.
    got = tops([card("apostlegrail.pillar1"),
                card("apostlegrail.pillar2.dormant"),
                card("apostlegrail.pillarfuel"), card("funds", qty=7)],
               legacy="apostlegrail")
    assert 170 in got and got[170].urgent
    assert "入梦" in got[170].detail
    # Active blood nearing decay is warned before it becomes dormant.
    got = tops([card("apostlegrail.pillar1"),
                card("apostlegrail.pillar2", lifetime=60),
                card("funds", qty=7)], legacy="apostlegrail")
    assert 150 in got and got[150].urgent


def test_lantern_apostle_route_and_allure_deadline():
    assert 125 in tops([card("legacyapostlelanternjob")], legacy="apostlelantern")
    # Crossroads + fuel + Splendour gives the concrete Allure step.
    got = tops([card("apostlelantern.pillar1"),
                card("apostlelantern.pillar2"),
                card("apostlelantern.pillarfuel"),
                card("influencelanterng"), card("funds", qty=7)],
               legacy="apostlelantern")
    assert 82 in got and "诱饵" in got[82].detail
    # The Allure expires and must be maintained with Fascination.
    got = tops([card("apostlelantern.pillar1"),
                card("apostlelantern.pillar2"),
                card("apostlelantern.pillar3", lifetime=60),
                card("fascination"), card("funds", qty=7)],
               legacy="apostlelantern")
    assert 150 in got and got[150].urgent
