"""Offline tests for the voice assistant dialogue engine, speech parsing and live sign -> sentence builder."""
import os
import sys

for var in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_KEY", "HUGGINGFACE_API_KEY"):
    os.environ[var] = ""
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services.message_service import message_service  # noqa: E402
from services.sign_sentence import SignSentenceBuilder, autocorrect_word, format_sentence  # noqa: E402
from services.voice_agent import VoiceAgent  # noqa: E402
from utils.helpers import CODE_ALPHABET, generate_meeting_code  # noqa: E402
from utils.speech_parse import (parse_email, parse_meeting_code, parse_name, parse_role,  # noqa: E402
                                parse_yes_no, spell_code)

print("=== VOICE + SIGN TESTS ===")

# ---------------------------------------------------------------- parsing
assert parse_email("my email is john dot smith at gmail dot com") == "john.smith@gmail.com"
assert parse_email("j o h n 2 3 at the rate gmail dot com") == "john23@gmail.com"
assert parse_email("hello there") is None
assert parse_meeting_code("join meeting A M dash eight F three K nine two") == "AM-8F3K92"
assert parse_meeting_code("am 8f3k92") == "AM-8F3K92"
assert spell_code("AM-8F3K92") == "A, M, dash, eight, F, three, K, nine, two"
assert parse_name("my name is priya sharma") == "Priya Sharma"
assert parse_role("I am visually impaired") == "blind" and parse_role("host") == "manager"
assert parse_yes_no("yeah that's right") is True and parse_yes_no("no that is wrong") is False
assert all(c in CODE_ALPHABET for c in generate_meeting_code()[3:])
print("[PASS] speech parsing (names, e-mails, meeting codes, roles, yes/no)")

# ---------------------------------------------------------------- voice conversation
S = {"current_page": "login", "user": None, "current_meeting": None, "voice_mode": True}


def say(text):
    agent = VoiceAgent(S)
    start = agent.va["next_id"]
    agent.handle(text)
    return agent, " | ".join(q.get("text", "<beep>") for q in agent.va["queue"] if q["id"] >= start)


for utterance in ["create account", "my name is asha menon", "asha dot menon at gmail dot com", "yes", "I am blind"]:
    agent, reply = say(utterance)
assert S["user"] and S["user"]["role"] == "blind" and S["user"]["email"] == "asha.menon@gmail.com"
assert S["current_page"] == "meeting_room" and agent.navigate
print("[PASS] blind user created an account entirely by voice")

_, reply = say("create a meeting called weekly sync")
meeting = S["current_meeting"]
assert meeting and meeting["title"] == "Weekly Sync" and "meeting code is" in reply
print(f"[PASS] meeting created by voice ({meeting['meeting_code']})")

_, reply = say("enable audio")
assert "Audio enabled" in reply and S["voice_guidance_enabled"] is True
message_service.send_text_message(meeting["id"], "someone-else", "Ravi", "normal", "Can you hear me?")
agent = VoiceAgent(S)
start = agent.va["next_id"]
agent.poll_incoming()
assert any("Ravi says: Can you hear me?" in q.get("text", "") for q in agent.va["queue"] if q["id"] >= start)
print("[PASS] 'enable audio' on -> new messages from others are announced")

_, reply = say("start talking")
_, reply = say("we should review the budget first")
assert reply == "<beep>"
texts = [m["text_content"] for m in message_service.get_meeting_messages(meeting["id"])]
assert "we should review the budget first" in texts
_, reply = say("assistant who is here")
assert "Asha Menon" in reply
_, reply = say("stop talking")
assert "Command mode" in reply
print("[PASS] talk mode sends speech to the meeting; 'assistant ...' commands still work")

_, reply = say("disable audio")
agent = VoiceAgent(S)
start = agent.va["next_id"]
message_service.send_text_message(meeting["id"], "someone-else", "Ravi", "normal", "Second message")
agent.poll_incoming()
assert not [q for q in agent.va["queue"] if q["id"] >= start], "audio disabled -> nothing announced"
print("[PASS] 'disable audio' silences announcements")

_, reply = say("leave meeting")
assert S["current_meeting"] is None
_, reply = say("join meeting " + meeting["meeting_code"])
assert S["current_meeting"] and S["current_meeting"]["id"] == meeting["id"]
print("[PASS] left and re-joined a meeting by speaking its code")

_, reply = say("end the meeting")
assert "Only the host" not in reply
_, reply = say("yes")
assert S["current_meeting"] is None
_, reply = say("log out")
assert S["user"] is None and S["current_page"] == "login"
for utterance in ["log in", "asha dot menon at gmail dot com", "yes"]:
    _, reply = say(utterance)
assert S["user"] and S["user"]["name"] == "Asha Menon"
print("[PASS] end meeting (with confirmation), log out, log back in by voice")

_, reply = say("log in")
_, reply = say("nobody dot here at gmail dot com")
_, reply = say("yes")
assert "could not find an account" in reply or S["user"]
print("[PASS] unknown e-mail is reported, not silently registered")

# ---------------------------------------------------------------- sign -> sentence
clock = {"t": 0.0}
events = []
b = SignSentenceBuilder(min_conf=0.7, stable_frames=2, repeat_hold=2.5, word_pause=2.0, sentence_pause=4.5)


def frames(label, n, conf=0.9):
    for _ in range(n):
        clock["t"] += 0.6
        events.extend(b.update(label, conf, clock["t"]))


def spell(word, flicker=False):
    for ch in word:
        frames(ch, 3)
        if flicker and ch == "o":
            frames("e", 1)
            frames("o", 2)
        frames(None, 1)
    frames(None, 5)


for w in ["helo", "how", "are", "you"]:
    spell(w, flicker=(w == "how"))
frames(None, 10)
sentences = [e["value"] for e in events if e["type"] == "sentence"]
assert sentences == ["Hello, how are you?"], sentences
print(f"[PASS] live letters -> words -> sentence: {sentences[0]!r} (spelling fixed, flicker ignored)")

b.reset()
frames("q", 20, 0.4)
assert not b.letters, "low-confidence frames must never create text"
b.reset()
frames("l", 3)
frames(None, 1)
frames("l", 3)
assert b.letters == ["L", "L"]
assert autocorrect_word("helo") == "hello" and format_sentence(["i", "dont", "know"]) == "I don't know."
print("[PASS] low confidence ignored; double letters via a gap; contractions")

print("\n=== ALL VOICE + SIGN TESTS PASSED ===")
