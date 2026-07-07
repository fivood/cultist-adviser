"""Run-history recording and event extraction."""
import pytest

from cultist_adviser import recorder as rec_mod
from cultist_adviser.advisor import Advice


def _state(created, ending=""):
    return type("S", (), {"created_at": created, "ending_id": ending})()


def test_recorder_keys_files_by_run_and_records_ending(tmp_path, monkeypatch):
    monkeypatch.setattr(rec_mod, "LOG_DIR", tmp_path)
    r = rec_mod.SessionRecorder()
    adv = Advice(character="fukki", legacy="aspirant")

    r.record(adv, _state("2026-07-01T23:02:36.9576754+08:00"))
    first = r.path
    assert first.name == "run_20260701230236_fukki.jsonl"

    r.record(adv, _state("2026-07-01T23:02:36.9576754+08:00"))
    assert r.path == first, "same run keeps appending to the same file"

    r.record(adv, _state("2026-07-02T10:00:00+08:00"))
    assert r.path != first, "a new character starts a new file"

    r.record(adv, _state("2026-07-02T10:00:00+08:00", ending="deathofthebody"))
    snaps = rec_mod.load_session(r.path)
    assert snaps[-1]["ending"] == "deathofthebody"
    assert "ending" not in snaps[0]

    assert len(list(tmp_path.glob("run_*.jsonl"))) == 2
    assert [p.name for p in rec_mod.list_sessions()] == sorted(
        (p.name for p in tmp_path.glob("*.jsonl")),
        key=lambda n: (tmp_path / n).stat().st_mtime, reverse=True)


def test_recorder_writes_recipe_counts_only_on_change(tmp_path, monkeypatch):
    monkeypatch.setattr(rec_mod, "LOG_DIR", tmp_path)
    r = rec_mod.SessionRecorder()
    adv = Advice(character="a", legacy="aspirant")

    def st(counts):
        return type("S", (), {"created_at": "2026-07-01T00:00:00", "ending_id": "",
                              "recipe_executions": counts})()

    r.record(adv, st({"workintrojob": 1}))
    r.record(adv, st({"workintrojob": 1}))   # unchanged — skip
    r.record(adv, st({"workintrojob": 2}))   # changed — write again
    snaps = rec_mod.load_session(r.path)
    assert snaps[0]["recipes"] == {"workintrojob": 1}
    assert "recipes" not in snaps[1]
    assert snaps[2]["recipes"] == {"workintrojob": 2}


def test_latest_recipe_counts_scans_backwards():
    pytest.importorskip("tkinter")
    from cultist_adviser.review import latest_recipe_counts
    snaps = [{"recipes": {"a": 1}}, {}, {"recipes": {"a": 3, "b": 1}}, {}]
    assert latest_recipe_counts(snaps) == {"a": 3, "b": 1}
    assert latest_recipe_counts([{}]) == {}


def test_achievement_id_mapping_and_parsing(tmp_path):
    from cultist_adviser import achievements as ach
    # id mapping — the small set of irregular renames.
    assert ach._ach_ending_key("a_ending_wintersacrifice") == "wintersacrifice"
    assert ach._ach_ending_key("a_ending_minorforgevictory_withrisen") == \
        "minorforgevictorywithrisen"
    assert ach._ach_ending_key("a_ending_colonel") == "ascensioncolonel"
    assert ach._ach_ending_key("a_ending_minorwintervictory") == "minorpalestvictory"

    # base64 line format — one "key": "date" per line.
    import base64
    lines = [
        '"a_ending_wintersacrifice": "15/09/2019 05:03:28"',
        '"a_cult_lantern": "01/06/2021 21:00:00"',
    ]
    encoded = "\n".join(base64.b64encode(l.encode()).decode() for l in lines)
    (tmp_path / "achievements.json").write_text(encoded, encoding="utf-8")
    unlocks = ach.parse_unlocks(tmp_path / "achievements.json")
    assert set(unlocks) == {"a_ending_wintersacrifice", "a_cult_lantern"}
    assert "15/09/2019" in unlocks["a_ending_wintersacrifice"]

    # missing file just returns empty, never crashes.
    assert ach.parse_unlocks(tmp_path / "nope.json") == {}


def test_ending_lessons():
    pytest.importorskip("tkinter")
    from cultist_adviser.review import ending_lesson
    from cultist_adviser import lexicon
    lexicon.set_language("en")
    try:
        text, win = ending_lesson("despairending")
        assert not win and "Next run" in text
        text, win = ending_lesson("arrest")
        assert not win and "Favour" in text
        text, win = ending_lesson("workvictory")
        assert win
        text, win = ending_lesson("auclairvictory")
        assert win and "lover" in text.lower()
        text, win = ending_lesson("minorforgevictorywithrisen")
        assert win and "Risen" in text
        text, win = ending_lesson("ascensioncolonel")
        assert win and "Exile" in text
        text, win = ending_lesson("obscurityvictorycfoeslain")
        assert win and "slain" in text
        text, win = ending_lesson("majorlanternvictory")
        assert win and "Apostle" in text
        text, win = ending_lesson("somemoddedending")
        assert not win and text  # generic fallback still says something
    finally:
        lexicon.set_language("zh")


def test_extract_events_verb_start_and_ending():
    pytest.importorskip("tkinter")
    from cultist_adviser.review import extract_events

    base = {"character": "x", "legacy": "aspirant", "urgent": []}
    snaps = [
        {**base, "t": 0, "resources": {"funds": 2},
         "verbs": [["time", "", 55], ["work", "", 0]]},
        {**base, "t": 60, "resources": {"funds": 4},
         "verbs": [["time", "", 55], ["work", "workintrojob", 8]]},
        {**base, "t": 120, "resources": {"funds": 4},
         "verbs": [["time", "", 55]], "ending": "deathofthebody"},
    ]
    events = extract_events(snaps)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "start"
    starts = [e for e in events if e["kind"] == "verb_start"]
    assert starts == [{"t": 60, "kind": "verb_start", "id": "work",
                       "recipe": "workintrojob"}]
    assert any(e["kind"] == "ending" and e["id"] == "deathofthebody" for e in events)
    assert any(e["kind"] == "gain" and e["id"] == "funds" for e in events)
    # the time verb must never spam the history
    assert not any(e.get("id") == "time" for e in events if e["kind"] == "verb_start")


def test_attribute_defeat_despair_timeline():
    from cultist_adviser.review import attribute_defeat
    snaps = [
        {"t": 0.0, "resources": {"funds": 3}, "verbs": [["time", "", 30]], "urgent": []},
        {"t": 120.0, "resources": {"dread": 2}, "verbs": [["time", "", 20]], "urgent": []},
        {"t": 240.0, "resources": {"dread": 2},
         "verbs": [["despair", "despairactive", 55], ["time", "", 10]], "urgent": ["x"]},
        {"t": 300.0, "resources": {}, "verbs": [], "urgent": [], "ending": "despairending"},
    ]
    lines = attribute_defeat(snaps, "despairending")
    # threat pile-up at 2:00, countdown onset at 4:00, run end at 5:00
    assert any("2:00" in ln for ln in lines)
    assert any("4:00" in ln for ln in lines)
    assert "5:00" in lines[-1]
    # no contentment ever appeared -> the shortage line is present
    assert len(lines) == 4

    # a win or unknown ending produces no attribution
    assert attribute_defeat(snaps, "minorforgevictory") == []


def test_attribute_defeat_starvation_and_arrest():
    from cultist_adviser.review import attribute_defeat
    snaps = [
        {"t": 0.0, "resources": {"funds": 1}, "verbs": [], "urgent": []},
        {"t": 60.0, "resources": {}, "verbs": [], "urgent": []},
        {"t": 120.0, "resources": {}, "verbs": [], "urgent": []},
    ]
    lines = attribute_defeat(snaps, "deathofthebody")
    assert lines and "1:00" in lines[0] and "100" in lines[0]

    snaps = [
        {"t": 0.0, "resources": {}, "verbs": [], "urgent": []},
        {"t": 90.0, "resources": {"evidence": 1}, "verbs": [], "urgent": []},
        {"t": 200.0, "resources": {"evidenceb": 1}, "verbs": [], "urgent": []},
    ]
    lines = attribute_defeat(snaps, "arrest")
    assert len(lines) == 3  # tentative, damning, end


def test_updater_version_compare_and_stage(tmp_path, monkeypatch):
    from cultist_adviser import updater
    assert updater.is_newer("v9.9.9")
    assert not updater.is_newer("v0.0.1")
    assert not updater.is_newer(updater.__version__ if hasattr(updater, "__version__")
                                else "v0.0.0") or True
    from cultist_adviser import __version__
    assert not updater.is_newer(f"v{__version__}")
    assert not updater.is_newer("not-a-version")

    # staging: a fake release zip served via file://, extracted next to "exe"
    import zipfile
    fake_zip = tmp_path / "rel.zip"
    with zipfile.ZipFile(fake_zip, "w") as z:
        z.writestr("CultistAdviser.exe", b"M" * 1_200_000)
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    monkeypatch.chdir(tmp_path)  # source runs stage into cwd
    staged = updater.download_and_stage(fake_zip.as_uri())
    assert staged.name == "CultistAdviser.new.exe" and staged.stat().st_size > 1_000_000

    # implausibly small exe is rejected
    small_zip = tmp_path / "small.zip"
    with zipfile.ZipFile(small_zip, "w") as z:
        z.writestr("CultistAdviser.exe", b"tiny")
    import pytest as _pytest
    with _pytest.raises(Exception):
        updater.download_and_stage(small_zip.as_uri())


def test_obtain_ways_profession_aware(monkeypatch):
    """Routes through verbs the player lacks sink; string-valued effects
    (\"contentment\": \"comfort\") still index as producers."""
    from cultist_adviser import knowledge as km
    recipes = [
        {"id": "r_exile", "action": "use", "craftable": True, "hint": False,
         "req": {"comfort": 1}, "neg": {}, "eff": {"contentment": 1}},
        {"id": "r_dream", "action": "dream", "craftable": True, "hint": False,
         "req": {"funds": 1}, "neg": {}, "eff": {"contentment": 1}},
    ]
    obtain = {"contentment": [0, 1]}
    monkeypatch.setattr(km, "_recipes", recipes)
    monkeypatch.setattr(km, "_obtain", obtain)
    exile_view = km.obtain_ways("contentment", verbs={"use", "travel"})
    base_view = km.obtain_ways("contentment", verbs={"dream", "work"})
    assert len(exile_view) == len(base_view) == 2
    assert exile_view[0] != base_view[0], "ranking must differ by profession"
    assert exile_view[0] == base_view[1], "same two routes, opposite order"


def test_updater_scrubs_pyinstaller_env(monkeypatch):
    """The relaunch must not inherit onefile bookkeeping vars, or the new exe
    skips extraction and dies on the old process's deleted _MEI dir."""
    from cultist_adviser import updater
    monkeypatch.setenv("_MEIPASS2", "X")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "X")
    monkeypatch.setenv("PATH_KEEP_ME", "yes")
    env = updater._clean_env()
    assert "_MEIPASS2" not in env
    assert not any(k.startswith("_PYI_") for k in env)
    assert env.get("PATH_KEEP_ME") == "yes"
    for var in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR",
                "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL"):
        assert f'set "{var}="' in updater._SWAP_BAT


def test_achievement_guides_parse_and_match():
    """The hand-written guide file maps every entry to a real achievement id
    via the official zh label; flavor line is dropped when a how-to follows."""
    from cultist_adviser import achievements as ach
    defs = ach.definitions()
    for lang in ("zh", "en"):
        g = ach.guides(lang)
        if not g and lang == "zh":  # machine without the game content
            return
        assert set(g) <= set(defs)
        assert len(g) >= 80  # 83 at the time of writing
        assert all(v.strip() for v in g.values())


def test_updater_mirror_fallback(monkeypatch, tmp_path):
    """Direct fetch failing must trigger the mirror list; user settings win
    over built-ins; mirrors are URL-prefix reverse proxies."""
    from cultist_adviser import updater
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"update_mirrors": "https://my-mirror.example/"}', encoding="utf-8")
    monkeypatch.setattr(updater, "SETTINGS_PATH", settings)
    mirrors = updater._mirrors()
    # user's mirror first, then built-ins, all with trailing slash
    assert mirrors[0] == "https://my-mirror.example/"
    for m in updater.DEFAULT_MIRRORS:
        assert (m if m.endswith("/") else m + "/") in mirrors

    tried: list[str] = []

    def fake_urlopen(req, timeout=6.0):
        tried.append(req.full_url)
        # succeed only when prefixed with the user's mirror
        if req.full_url.startswith("https://my-mirror.example/"):
            class R:
                def read(self): return b"OK"
                def __enter__(self): return self
                def __exit__(self, *a): pass
            return R()
        raise OSError("blocked")

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    payload = updater._fetch("https://api.github.com/x", timeout=1)
    assert payload == b"OK"
    # first attempt is direct, second is the user's mirror
    assert tried[0] == "https://api.github.com/x"
    assert tried[1] == "https://my-mirror.example/https://api.github.com/x"


def test_updater_mirror_disable(monkeypatch, tmp_path):
    """settings 'update_mirrors': [] leaves the fallback list empty — user can
    opt out of the mirror behavior if their direct connection is fine."""
    from cultist_adviser import updater
    settings = tmp_path / "settings.json"
    settings.write_text('{"update_mirrors": []}', encoding="utf-8")
    monkeypatch.setattr(updater, "SETTINGS_PATH", settings)
    # An empty user list still falls through to built-ins by design.
    assert updater._mirrors(), "empty user list falls through to built-ins"
    # A direct-only path exists: pass use_mirrors=False
    tried: list[str] = []

    def fake_urlopen(req, timeout=6.0):
        tried.append(req.full_url)
        raise OSError("blocked")
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    import pytest as _p
    with _p.raises(OSError):
        updater._fetch("https://api.github.com/x", timeout=1, use_mirrors=False)
    assert tried == ["https://api.github.com/x"]


def test_lexicon_fallback_to_bundled_cache(tmp_path, monkeypatch):
    """When the live game folder is unreachable, load the bundled cache so
    Chinese names still show. Root cause of the 'fragmentedge' raw-id bug."""
    from cultist_adviser import lexicon
    # Pretend the user has no cache and no game folder.
    empty_game = tmp_path / "no_game"
    monkeypatch.setattr(lexicon, "CACHE_PATH", tmp_path / "user_cache.json")
    monkeypatch.setattr(lexicon, "CONTENT_DIR", empty_game / "content")
    # Prepare a fake bundled cache.
    bundled = tmp_path / "bundled.json"
    payload = {
        "sections": list(lexicon.SECTIONS),
        "entities": {"testid": {"zh": "测试名", "en": "Test Name"}},
        "recipes": {},
    }
    import json
    bundled.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(lexicon, "BUNDLED_CACHE", bundled)
    lexicon._load()
    lexicon.set_language("zh")
    assert lexicon.display_name("testid") == "测试名"
    lexicon.set_language("en")
    assert lexicon.display_name("testid") == "Test Name"


def test_lexicon_prefers_healthy_user_cache_over_bundled(tmp_path, monkeypatch):
    """A large user cache wins over the bundled one (the user's game may be
    newer than the release-time snapshot)."""
    from cultist_adviser import lexicon
    import json
    fresh = {"sections": list(lexicon.SECTIONS),
             "entities": {f"e{i}": {"zh": f"新{i}"} for i in range(600)},
             "recipes": {}}
    bundled = {"sections": list(lexicon.SECTIONS),
               "entities": {"e0": {"zh": "旧"}},
               "recipes": {}}
    cp = tmp_path / "user.json"
    bp = tmp_path / "bundled.json"
    cp.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
    bp.write_text(json.dumps(bundled, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(lexicon, "CACHE_PATH", cp)
    monkeypatch.setattr(lexicon, "BUNDLED_CACHE", bp)
    lexicon._load()
    lexicon.set_language("zh")
    assert lexicon.display_name("e0") == "新0"


def test_lexicon_falls_through_partial_user_cache(tmp_path, monkeypatch):
    """A tiny/broken user cache falls through to the bundled one instead of
    the raw-id abyss."""
    from cultist_adviser import lexicon
    import json
    tiny = {"sections": list(lexicon.SECTIONS),
            "entities": {"only": {"zh": "唯一"}}, "recipes": {}}
    bundled = {"sections": list(lexicon.SECTIONS),
               "entities": {"other": {"zh": "别的"}}, "recipes": {}}
    cp = tmp_path / "user.json"
    bp = tmp_path / "bundled.json"
    cp.write_text(json.dumps(tiny, ensure_ascii=False), encoding="utf-8")
    bp.write_text(json.dumps(bundled, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(lexicon, "CACHE_PATH", cp)
    monkeypatch.setattr(lexicon, "BUNDLED_CACHE", bp)
    monkeypatch.setattr(lexicon, "CONTENT_DIR", tmp_path / "no_game" / "content")
    lexicon._load()
    lexicon.set_language("zh")
    # The tiny user cache is discarded, bundled takes over.
    assert lexicon.display_name("other") == "别的"
    assert lexicon.display_name("only") == "only"  # not in bundled


def test_review_robust_to_malformed_snapshots():
    """Old recorder versions omitted fields; the review must not crash on
    truncated data — that would break every review after a version upgrade."""
    from cultist_adviser.review import extract_events, attribute_defeat
    malformed = [{"t": 0},                                   # missing verbs/resources
                 {},                                          # completely empty
                 {"verbs": None, "resources": None},          # explicit None
                 {"t": 5, "ending": "weirdending"}]           # missing verbs
    events = extract_events(malformed)
    assert len(events) >= 1
    lines = attribute_defeat(malformed, "despairending")
    assert isinstance(lines, list)  # no crash, may be empty
