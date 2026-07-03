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
