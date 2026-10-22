"""Offline tests for 'Summarize Post Meeting' (in-memory DB, no network, no real keys): python test_summary.py"""
import io
import json
import os
import sys
import tempfile
import urllib.error

for var in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_KEY", "HUGGINGFACE_API_KEY", "GEMINI_API_KEY"):
    os.environ[var] = ""
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np  # noqa: E402

from services import audio_pipeline as ap  # noqa: E402
from services import summary_service as ss  # noqa: E402
from services.meeting_service import meeting_service  # noqa: E402
from services.message_service import message_service  # noqa: E402
from services.supabase_service import supabase_service  # noqa: E402
from services.user_service import user_service  # noqa: E402
from utils.config import Config  # noqa: E402

print("=== SUMMARY TESTS ===")

# ---------------------------------------------------------------- JSON extraction / normalisation
assert ss.extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
assert ss.extract_json_object('Sure! Here you go: {"a": {"b": 2}} hope it helps') == {"a": {"b": 2}}
assert ss.extract_json_object("no json here") is None
assert ss.extract_json_object("[1,2,3]") is None
n = ss.normalize_summary({"summary": "s", "action_items": [{"task": "Send deck"}, "Book room", {"task": ""}, 5],
                          "key_decisions": "Ship Friday", "topics_discussed": None}, "Fallback")
assert n["title"] == "Fallback" and n["key_decisions"] == ["Ship Friday"] and n["topics_discussed"] == []
assert n["action_items"][0] == {"task": "Send deck", "assigned_to": "Not specified", "deadline": "Not specified"}
assert [a["task"] for a in n["action_items"]] == ["Send deck", "Book room", "5"]
print("[PASS] JSON extraction and normalisation")

# ---------------------------------------------------------------- transcript building
ok, host, _ = user_service.register_user("Asha Host", "asha@test.com", "manager")
ok, mute, _ = user_service.register_user("Ravi Signs", "ravi@test.com", "mute")
ok, outsider, _ = user_service.register_user("Out Sider", "out@test.com", "normal")
ok, meeting, _ = meeting_service.create_meeting("Launch planning", host["id"])
meeting_service.join_meeting(meeting["meeting_code"], host["id"], "manager")
meeting_service.join_meeting(meeting["meeting_code"], mute["id"], "mute")
mid = meeting["id"]
message_service.send_system_message(mid, "Ravi joined")
message_service.send_text_message(mid, host["id"], host["name"], "manager",
                                  "We decided to launch the beta on Friday. Everyone agreed on the pricing plan.")
message_service.send_voice_text_message(mid, host["id"], host["name"], "manager",
                                        "Ravi will prepare the demo video by Thursday. Please review the launch checklist.")
message_service.process_and_send_sign_message(mid, mute["id"], mute["name"], "mute", "I will test the signup flow")
transcript, stats = ss.build_transcript(supabase_service.get_messages(mid))
assert "Ravi joined" not in transcript and transcript.count("\n") == 2
assert "Asha Host (manager, voice): Ravi will prepare" in transcript
assert stats["total_messages"] == 3 and stats["speakers"][0]["name"] == "Asha Host"
assert abs(sum(s["share"] for s in stats["speakers"]) - 100) < 0.5
assert stats["speakers"][1]["via"] == {"sign_language": 1}
print("[PASS] Transcript excludes system notices; per-speaker stats and input types correct")

# ---------------------------------------------------------------- offline engine (no keys)
summary, engine, warns = ss.summarize_text(transcript, "Launch planning")
assert engine.startswith("Offline") and any("No AI key" in w for w in warns)
assert any("Friday" in d for d in summary["key_decisions"]), summary
assert any("demo video" in a["task"] for a in summary["action_items"]), summary
assert summary["summary"] and summary["title"] == "Launch planning"
empty = ss.offline_summary("", "T")
assert "empty" in empty["summary"].lower()
print("[PASS] Offline fallback finds decision + action item, labelled as basic, handles empty input")

# ---------------------------------------------------------------- Gemini path (mocked network)
class _Resp:
    def __init__(self, payload): self._p = json.dumps(payload).encode()
    def read(self): return self._p
    def __enter__(self): return self
    def __exit__(self, *a): return False

captured = {}
def fake_ok(req, timeout=0):
    captured["url"], captured["headers"], captured["body"] = req.full_url, dict(req.header_items()), json.loads(req.data)
    reply = '```json\n{"title":"Beta launch","summary":"Beta ships Friday.","action_items":[{"task":"Demo video","assigned_to":"Ravi","deadline":"Thursday"}],"key_decisions":["Launch beta Friday"],"topics_discussed":["Launch","Pricing"]}\n```'
    return _Resp({"candidates": [{"content": {"parts": [{"text": reply}]}}]})

Config.GEMINI_API_KEY = "AIza-test-key"
ss.urllib.request.urlopen = fake_ok
summary, engine, warns = ss.summarize_text(transcript, "Launch planning")
assert engine.startswith("Gemini") and summary["title"] == "Beta launch" and not warns
assert "AIza-test-key" not in captured["url"], "API key must not be placed in the URL"
assert captured["headers"].get("X-goog-api-key") == "AIza-test-key"
assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
assert "Asha Host" in captured["body"]["contents"][0]["parts"][0]["text"]
print("[PASS] Gemini request/response handled (fences stripped, key sent in header)")

def fake_http_error(req, timeout=0):
    raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, io.BytesIO(b'{"error":{"message":"quota exceeded"}}'))
ss.urllib.request.urlopen = fake_http_error
summary, engine, warns = ss.summarize_text(transcript, "Launch planning")
assert engine.startswith("Offline") and any("quota exceeded" in w for w in warns), warns

def fake_garbage(req, timeout=0):
    return _Resp({"candidates": [{"content": {"parts": [{"text": "I cannot do that"}]}}]})
ss.urllib.request.urlopen = fake_garbage
summary, engine, warns = ss.summarize_text(transcript, "Launch planning")
assert engine.startswith("Offline") and any("not valid JSON" in w for w in warns), warns
ss.urllib.request.urlopen = fake_ok
print("[PASS] Gemini errors / non-JSON replies fall back to offline and say why")

# ---------------------------------------------------------------- end-to-end with storage
ok, rec, msg = ss.summary_service.summarize_meeting(meeting, generated_by=host["id"])
assert ok, msg
saved = ss.summary_service.get_saved(mid)
assert saved["engine"].startswith("Gemini") and saved["source"] == "conversation"
assert saved["summary"]["full_transcript"] == transcript and saved["summary"]["stats"]["total_messages"] == 3
assert ss.summary_service.user_took_part(meeting, host["id"]) and ss.summary_service.user_took_part(meeting, mute["id"])
assert not ss.summary_service.user_took_part(meeting, outsider["id"]), "non-participants must not see summaries"
assert [m["id"] for m in ss.summary_service.list_meetings(mute["id"])] == [mid]
assert ss.summary_service.list_meetings(outsider["id"]) == []
md = ss.summary_service.to_markdown(meeting, saved)
assert "# Beta launch" in md and "Demo video" in md and "Ravi" in md
spoken = ss.summary_service.to_spoken_text(saved)
assert "assigned to Ravi" in spoken and "due Thursday" in spoken and "#" not in spoken and "**" not in spoken
ok2, _, msg2 = ss.summary_service.summarize_meeting(meeting, generated_by=host["id"])   # regenerate replaces
assert ok2 and len(supabase_service._summaries) == 1
ok, meeting2, _ = meeting_service.create_meeting("Empty meeting", host["id"])
ok3, none, msg3 = ss.summary_service.summarize_meeting(meeting2, generated_by=host["id"])
assert not ok3 and "no conversation" in msg3.lower()
print("[PASS] Save / fetch / regenerate / access check / markdown / spoken text / empty meeting")

# ---------------------------------------------------------------- recording path (summary part only)
ok, rec, msg = ss.summary_service.summarize_recording(
    meeting, "Asha: We agreed to ship Friday.\nRavi: I will write the notes.",
    [{"name": "Asha", "seconds": 30.0}, {"name": "Ravi", "seconds": 10.0}], generated_by=host["id"])
assert ok and rec["source"] == "recording" and rec["summary"]["stats"]["speakers"][0]["share"] == 75.0
print("[PASS] Recording transcript summarised with talk-time shares")

# ---------------------------------------------------------------- audio pipeline pure logic
words = [{"word": " Hello", "start": 0.0, "end": 0.4}, {"word": " there", "start": 0.5, "end": 0.9},
         {"word": " hi", "start": 1.6, "end": 1.9}, {"word": " back", "start": 2.2, "end": 2.6},
         {"word": " in", "start": 3.1, "end": 3.3}, {"word": " pause", "start": 4.4, "end": 4.6}]
turns = [(0.0, 1.0, "SPEAKER_00"), (1.5, 2.0, "SPEAKER_01"), (2.0, 3.0, "SPEAKER_00")]
parts = ap.assign_words_to_turns(words, turns)
assert parts == [("SPEAKER_00", "Hello there"), ("SPEAKER_01", "hi"), ("SPEAKER_00", "back in pause")], parts
assert ap.assign_words_to_turns([], turns) == [] and ap.assign_words_to_turns(words, []) == []
t = ap.talk_seconds(turns, {"SPEAKER_00": "Asha", "SPEAKER_01": "Speaker 1"})
assert t[0] == {"name": "Asha", "seconds": 2.0} and t[1]["name"] == "Speaker 1"
a, b = np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
enrolled = [{"name": "Asha", "voiceprint": a}, {"name": "Ravi", "voiceprint": b}]
assert ap.match_voiceprint(np.array([0.9, 0.1, 0.0]), enrolled, 0.5) == "Asha"
assert ap.match_voiceprint(np.array([0.0, 0.0, 1.0]), enrolled, 0.5) is None
with tempfile.TemporaryDirectory() as d:
    Config.VOICEPRINT_DIR = d
    np.savez(os.path.join(d, "Asha_1.npz"), name=np.array("Asha"), voiceprint=a)
    with open(os.path.join(d, "evil.npz"), "wb") as f:
        f.write(b"not an npz")
    sp = ap.list_speakers()
    assert [s["name"] for s in sp] == ["Asha"], "corrupt voiceprint files are skipped"
    assert not ap.delete_speaker("/etc/passwd") and ap.delete_speaker(sp[0]["path"]) and ap.list_speakers() == []
print("[PASS] Word->speaker assignment, talk time, voiceprint matching and safe voiceprint storage")

print("\n=== ALL SUMMARY TESTS PASSED ===")
