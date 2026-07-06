# Cultist Adviser · 密教军师

[中文](README.zh-CN.md) | **English**

A read-only floating adviser for **Cultist Simulator**. It watches the save
file and offers prioritized suggestions for the current board — **advice only,
hands off**: no screen capture, no input simulation, no save editing. The game
window is never touched.

---

## Quick start

**Requirements**: Windows, with the game installed (the adviser reads
localized names and recipe data from the game's own files).

### No Python needed

Download the latest `CultistAdviser-vX.Y.Z.zip` from
[Releases](https://github.com/fivood/cultist-adviser/releases), unzip, and
double-click `CultistAdviser.exe`. A usage guide (中文) is included.

### Run from source

Python 3.10+ (standard library only):

```
python -m cultist_adviser
```

Build your own exe: `pip install pyinstaller`, then
`python -m PyInstaller --onefile --noconsole --name CultistAdviser launcher.py`.

### Path overrides

If auto-detection misses your install, set environment variables:

| Variable | Meaning | Default |
|---|---|---|
| `CULTIST_GAME_DIR` | game install folder | common Steam library locations |
| `CULTIST_SAVE_DIR` | save folder | `%USERPROFILE%\AppData\LocalLow\Weather Factory\Cultist Simulator` |

First launch writes two caches (`lexicon_cache.json` /
`knowledge_cache.json`) next to the program; delete them after a game update
to rebuild. Settings persist in `settings.json` (language, spoiler level).

---

## Three spoiler tiers

The adviser respects the occult experience of not knowing. Switch from the
top bar:

- **Keeper** — survival alerts only (things that kill you); fateful choices
  stay yours
- **Counsel** (default) — guidance without foretelling outcomes: expedition
  obstacles show only after scouting, the seasons deck reports card counts
  only, bequests are flagged but not spoiled
- **Revelation** — the all-seeing eye: hidden piles, choice outcomes, and
  bookshop stock laid bare

Suppressed hints show as a count; switch any time. Settings persist locally.

---

## Features

**Danger alerts** — Despair/Visions death countdowns, trials in progress,
Poppy's summons, lethal sickness, Long assassinations/raids/duels, rival
ascension rites, evidence/hunters, affliction/restlessness/hunger, funds
watermark. Every lethal verb is highlighted in red.

**Seasons** — reads the next season already drawn into the Time verb and
warns when you're unprepared (including the Ambition season's tribute
check); sees what the seasons deck still holds, so dread/fascination
stockpile alerts soften automatically once Despair/Visions are exhausted
this cycle. At Revelation tier it goes further: **the exact order of the
remaining seasons with arrival estimates**. The pile's stored order *is*
the draw order (the engine shuffles only on refill), so this is prophecy,
not probability — "two more Despairs, in ~4 and ~5 minutes". An
**always-visible season strip** sits under the top bar and turns red when
the next season arrives without a counter ready.

**Recipe scanner ("what can I start right now")** — simulates actual
slotting per the engine's `SphereSpec.cs`: the pivot card must fit the
verb's primary slot (any one required aspect at value qualifies, any
forbidden aspect blocks, per-unit aspects), placed cards recursively open
the slots their elements define, and same-name copies stack in a single
slot with aspects multiplied (that's how "Contentment ×2 = Heart 4" is
actually formed in-game). Idle-verb suggestions list "ingredients ready"
recipes with the exact cards to use; **double-click a verb row** for the
full startable list.

**Decay chains** — decay targets read from game data: timed cards are
labeled with where their countdown leads ("Restlessness → Dread"), so you
can tell at a glance which timers to fear. Expiry warnings split by
outcome — degradations are named ("becomes Dread when it expires"),
harmless transformations (Fatigue back into Health) stop nagging. The card
dialog shows the full decay chain.

**Opening walkthroughs** — all 4 base professions (Aspirant / Detective /
Bright Young Thing / Physician) + 4 DLC starts (Dancer / Priest / Ghoul /
Exile), stepped by each legacy's own plot cards, every number checked
against the game's recipe JSON.

**Mid/late game progression** — cult-founding checklist (missing an
acquaintance or the lore? one line says which), Ambition 1→6 stage checks,
Mansus door-by-door requirements against your actual lore, exact Stag Door
riddle answers, rival (Long candidate) warnings with proactive counterplay
during their scheming window, endgame accounting (primary lore X/36 —
**it says so when you have enough**).

**Recruitment planning** — affinity overview for acquaintances on the board
(all 23 NPCs have fixed leanings); when the cult lacks a key Moth/Edge
follower, it names who to recruit.

**Exile survival** — dedicated rules for the Exile DLC: wound treatment,
foe-minion alerts, Trace accumulation (a mechanic set entirely unlike the
base game).

**Stage banner** — the adviser infers your current main line (making a
living → founding a cult → dedication → Stag Door → Ambition seasons →
ascension) and keeps a one-line "current stage" always visible. Glance at
it instead of alt-tabbing to a wiki.

**Defeat analysis** — when a run ends, the review window explains the death
in plain words with prevention notes for next time. All 63 endings defined
by the game have bespoke epilogues (21 marriage endings, standard
ascensions, DLC lines) — turning "died again" into "learned something".
Despair/Visions/arrest/starvation losses also get a **timeline attribution
from this run's own snapshots**: when the threat piled up, how long the
counter was missing, when the countdown began — a chain that shows
exactly how you lost.

**Books & languages counsel** — unreadable books grouped by language with
ways to get the scholar card; bookshop stock and textbooks on sale (empty
the shop to gain the room); idle Study prefers readable/translatable books.

**Lore upgrade calculator** — when Ambition 2→3 needs a level-6 lore, it
computes the shortest path from your actual fragments (same-type upgrade /
subversion / collect from scratch).

**Expedition planning** — with a vault on the board, every obstacle is
listed with its countering aspects (all 41 base-game sites covered) and
success odds computed from your followers' actual aspect levels
(guaranteed / ~70% / ~30% / hard fail).

**Follower assignments** — destroying evidence or attacking hunters shows
real success rates and failure costs based on your followers' Moth/Edge/
Winter levels.

**Idle verb suggestions** — the best current use for every idle verb, with
reasons, plus the ingredients-ready startable recipes.

**Board resource table** — a collapsible tree grouped by category
(threats / resources / fragments / lore / influences / books / people /
places / misc), sorted by expiry within groups; a filter box and a
"timed only" toggle; same-name cards expand to individual countdowns;
timed cards labeled with their decay target; double-click any card for the
card dialog (**Uses** + **How to obtain** tabs, decay chain on top).
Cooldown-state cards (fatigue, exhausted, recovering followers/weapons)
are marked blue and never nagged about.

**Tiered suggestion panel** — ⚠ urgent / ● advice / ○ intel, visually
distinct; crises always on top, background intel resting quietly below.
Optional alert sound: a system beep whenever a new urgent alert appears
(hear the crisis without watching the window in fullscreen). **Right-click
any non-urgent suggestion to mute it** — identity is priority plus the
title with digits masked, so a ticking countdown won't resurrect a muted
line but a real board change will. Urgent alerts cannot be muted.

**Live refresh** — detects changes by reading save content, not file
timestamps (Windows delays timestamp updates, which used to require
alt-tabbing; fixed).

**Pause awareness** — when the save is overdue, the game is presumed
paused and countdowns freeze.

**Run history & review** — records the whole run per character (keyed by
save creation time), from fresh start to ending, resuming across GUI
restarts. Event timeline: every action choice (verb + recipe), key card
gains/losses, crises from onset to resolution, the final ending. Action
statistics from the save's own recipe-execution counters. Resource trend
chart and summary stats.

**Steam achievement tracking** — reads the game's local achievement record
(that base64-encoded file in the save folder): the review window shows
progress `N/83` with locked ones grouped by category; during play, if the
current board is already on track toward a locked achievement (founded the
matching cult, opened a new Mansus door, exalted a disciple, summoned a
spirit), the adviser quietly notes "achievable this run: X". Skipped at
Keeper tier — achievements are a metagame pull that bends route freedom.

**Bilingual** — card/verb names come from the game's own Chinese/English
localization; the UI switches with one click.

---

## Credits & license

- MIT License.
- Some rules ported from
  [autoccultist](https://github.com/SunsetFi/autoccultist)'s brain-config
  (MIT License, Copyright 2020 RoboPhredDev)
- Engine behaviors (season draw order, etc.) verified against the official
  source mirror
  [applers/cultistsimulator](https://github.com/applers/cultistsimulator)
- Strategy notes in
  [docs/strategy_knowledge.md](docs/strategy_knowledge.md), sourced from
  Steam community guides and the Fandom wiki
- Cultist Simulator © Weather Factory. This project is unaffiliated with
  Weather Factory and ships no game assets; at runtime it reads the
  player's locally installed game content.
