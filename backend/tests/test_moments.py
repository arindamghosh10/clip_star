import json
from types import SimpleNamespace

import pytest

from clipstar.engines.moments_engines import ClaudeMomentEngine, RulesMomentEngine, _EngineDeclined
from clipstar.errors import RetryableError
from clipstar.pipeline.moments import MomentSettings, Signals, build_sentences, finalize, hook_strength, make_hook, make_title


def _tr(lines):
    """lines: [(start, end, text)] -> transcript with evenly spread words"""
    segs = []
    for a, b, text in lines:
        toks = text.split()
        step = (b - a) / len(toks)
        segs.append({"start": a, "end": b, "text": text, "words": [{"start": a + i * step, "end": a + (i + 1) * step, "word": t} for i, t in enumerate(toks)]})
    return {"duration": lines[-1][1] + 1, "segments": segs}


TALK = _tr(
    [
        (0, 5, "Welcome back to the channel everyone."),
        (5, 10, "So today we have a guest with us."),
        (10, 15, "And we talk about many things."),
        (20, 24, "Nobody tells you this about rent?"),
        (24, 32, "I lost forty dollars a month for three years because of one line."),
        (32, 40, "Check your lease for the admin fee and ask them to remove it."),
        (40, 44, "That is the whole trick."),
        (50, 55, "Anyway let me know in the comments."),
        (55, 60, "Thanks for watching and see you next week."),
    ]
)
ST = MomentSettings(min_s=12, max_s=30, target_s=22, max_clips=3, min_score=0)


class Ctx:
    attempt = 1

    def progress(self, *a, **k):
        pass

    def check(self):
        pass


def test_sentences_split_on_punctuation_and_pauses():
    tr = {"segments": [{"start": 0, "end": 6, "text": "", "words": [
        {"start": 0, "end": 0.5, "word": "Hello"}, {"start": 0.5, "end": 1, "word": "there."},
        {"start": 1.1, "end": 1.5, "word": "Big"}, {"start": 3.0, "end": 3.5, "word": "pause"}]}]}
    s = build_sentences(tr)
    assert [x.text for x in s] == ["Hello there.", "Big", "pause"]


def test_hook_strength_prefers_questions_numbers_and_strong_words():
    strong, why = hook_strength("Nobody tells you this about rent?")
    weak, _ = hook_strength("So anyway we were talking.")
    assert strong > 0.6 > weak and "opens with a question" in why
    assert make_hook("So, nobody tells you this about rent?") == "NOBODY TELLS YOU"
    assert make_title("and so the biggest mistake is this") == "The biggest mistake is this"


def test_rules_engine_finds_the_hooky_story_and_skips_the_intro():
    sents = build_sentences(TALK)
    cands, notes = RulesMomentEngine().find(Ctx(), sents, Signals({"window_s": 1, "values": [0.2] * 61, "peaks": [26]}, []), ST, 61)
    final, _ = finalize(cands, sents, ST, 61)
    best = final[0]
    assert best.start == 20 and 12 <= best.duration <= 30
    assert "question" in best.reason.lower()
    for a in final:  # no overlaps
        for b in final:
            if a is not b:
                assert min(a.end, b.end) - max(a.start, b.start) < 0.25 * min(a.duration, b.duration)


def test_banned_topics_are_dropped():
    sents = build_sentences(TALK)
    st = MomentSettings(min_s=12, max_s=30, target_s=22, max_clips=5, min_score=0, banned_topics=["lease"])
    cands, _ = RulesMomentEngine().find(Ctx(), sents, Signals(None, []), st, 61)
    final, notes = finalize(cands, sents, st, 61)
    assert all("lease" not in " ".join(s.text for s in sents[c.start_id : c.end_id + 1]).lower() for c in final)
    assert any("lease" in n for n in notes)


def test_no_speech_uses_energy_peaks():
    cands, notes = RulesMomentEngine().find(Ctx(), [], Signals({"window_s": 1, "values": [0.1] * 120, "peaks": [60]}, [45.0]), ST, 120)
    final, _ = finalize(cands, [], ST, 120)
    assert len(final) == 1 and final[0].start <= 60 <= final[0].end and "No speech" in notes[0]


# ---------- Claude engine (no network: call() is replaced) ----------


def _claude(monkeypatch, answers):
    e = ClaudeMomentEngine()
    monkeypatch.setattr(e, "check", lambda: SimpleNamespace(ok=True, message=""))
    it = iter(answers)

    def call(system, prompt):
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a

    monkeypatch.setattr(e, "call", call)
    return e


def _ans(*clips):
    return json.dumps({"clips": [dict(start_id=a, end_id=b, title="Rent trap", hook="RENT TRAP", reason="Strong story", score=s) for a, b, s in clips]})


def test_claude_valid_answer_is_used_and_blended():
    sents = build_sentences(TALK)
    e = _claude(monkeypatch=pytest.MonkeyPatch(), answers=[_ans((3, 5, 90))])
    cands, notes = e.find(Ctx(), sents, Signals(None, []), ST, 61)
    assert len(cands) == 1 and cands[0].engine == "claude" and cands[0].start == 20 and cands[0].title == "Rent trap"
    assert 0 < cands[0].score <= 100 and cands[0].features["ai_score"] == 90 and notes == []


def test_claude_bad_answer_gets_one_repair_then_falls_back(monkeypatch):
    sents = build_sentences(TALK)
    e = _claude(monkeypatch, ["not json", _ans((99, 120, 80))])  # garbage, then impossible ids
    cands, notes = e.find(Ctx(), sents, Signals(None, []), ST, 61)
    assert cands and all(c.engine == "rules" for c in cands)
    assert "didn't return usable moments" in notes[0]


def test_claude_repair_succeeds(monkeypatch):
    sents = build_sentences(TALK)
    e = _claude(monkeypatch, [_ans((0, 0, 50)), _ans((3, 5, 88))])  # first clip too short -> repair
    cands, notes = e.find(Ctx(), sents, Signals(None, []), ST, 61)
    assert [c.engine for c in cands] == ["claude"]


def test_claude_declined_or_unconfigured_falls_back(monkeypatch):
    sents = build_sentences(TALK)
    e = _claude(monkeypatch, [_EngineDeclined("the API key was rejected")])
    cands, notes = e.find(Ctx(), sents, Signals(None, []), ST, 61)
    assert cands[0].engine == "rules" and "API key was rejected" in notes[0]

    e2 = ClaudeMomentEngine()
    monkeypatch.setattr(e2, "_key", lambda: None)
    cands, notes = e2.find(Ctx(), sents, Signals(None, []), ST, 61)
    assert cands[0].engine == "rules" and "isn't set up" in notes[0]


def test_claude_temporary_error_retries_job_until_last_attempt(monkeypatch):
    sents = build_sentences(TALK)
    e = _claude(monkeypatch, [RetryableError("429")])
    with pytest.raises(RetryableError):
        e.find(Ctx(), sents, Signals(None, []), ST, 61)
    last = Ctx()
    last.attempt = 99
    e = _claude(monkeypatch, [RetryableError("429")])
    cands, notes = e.find(last, sents, Signals(None, []), ST, 61)
    assert cands[0].engine == "rules" and "unavailable" in notes[0]


def test_workspace_settings_are_sanitised():
    st = MomentSettings.from_workspace({"clip_min_s": 1, "clip_max_s": 9999, "max_clips": 500, "banned_topics": ["crypto", " "]})
    assert st.min_s == 5 and st.max_s == 180 and st.max_clips == 30 and st.banned_topics == ["crypto"]


def test_intros_outros_and_sponsor_reads_score_low():
    tr = _tr([
        (0, 6, "Welcome back to the channel, money lovers."),
        (6, 14, "This video is brought to you by our sponsor."),
        (20, 26, "Here is the biggest money mistake you can make?"),
        (26, 34, "You pay a forty dollar fee every month without knowing."),
        (34, 40, "Thanks for watching and see you next week."),
    ])
    sents = build_sentences(tr)
    cands, _ = RulesMomentEngine().find(Ctx(), sents, Signals(None, []), ST, 41)
    final, _ = finalize(cands, sents, ST, 41)
    best = final[0]
    assert best.start == 20 and best.end == 34  # the story, without the outro
    intro = next(c for c in cands if c.start_id == 0)
    assert intro.features["housekeeping"] >= 1 and intro.score < best.score - 20
