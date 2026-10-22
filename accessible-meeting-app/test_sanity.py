"""Offline sanity test: forces in-memory DB and no AI keys so it never touches your real keys."""
import os
import sys

# Must be set BEFORE importing app modules (load_dotenv does not override existing variables).
for var in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_KEY", "HUGGINGFACE_API_KEY"):
    os.environ[var] = ""

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image  # noqa: E402

print("=== RUNNING SANITY TEST FOR ACCESSIBLE MEETING APP ===")

from models.schemas import InputType, Meeting, Message, UserProfile, UserRole  # noqa: E402,F401
from services.huggingface_service import huggingface_service  # noqa: E402
from services.meeting_service import meeting_service  # noqa: E402
from services.message_service import message_service  # noqa: E402
from services.supabase_service import supabase_service  # noqa: E402
from services.user_service import user_service  # noqa: E402
from utils.validation import validate_meeting_code  # noqa: E402

assert not supabase_service.use_supabase and not huggingface_service.is_live
print("[PASS] Imports OK (in-memory DB, no AI keys)")

ok, user, msg = user_service.register_user("Test Manager", "manager@test.com", "manager")
assert ok and user, msg
ok2, same, _ = user_service.login_user("Ignored", "manager@test.com")
assert ok2 and same["id"] == user["id"], "login must reuse the existing profile"
print(f"[PASS] User registered + re-login reuses profile ({user['id']})")

ok, meeting, msg = meeting_service.create_meeting("Test Accessibility Meeting", user["id"])
assert ok and meeting, msg
assert validate_meeting_code(meeting["meeting_code"])
print(f"[PASS] Meeting created: {meeting['meeting_code']}")

ok, _m, _p, msg = meeting_service.join_meeting(meeting["meeting_code"], user["id"], "manager")
assert ok, msg
assert len(meeting_service.get_participants(meeting["id"])) == 1
print("[PASS] Host joined (by code)")

ok, txt, msg = message_service.send_text_message(meeting["id"], user["id"], user["name"], "manager", "Welcome everyone!")
assert ok, msg
ok, _s, msg = message_service.process_and_send_sign_message(meeting["id"], user["id"], user["name"], "mute", "HELLO", 0.95)
assert ok, msg
ok, _v, msg = message_service.process_and_send_voice_message(meeting["id"], user["id"], user["name"], "normal", b"x" * 500)
assert not ok, "garbage audio must be rejected, never turned into fake text"
message_service.send_system_message(meeting["id"], "system hello")
assert len(message_service.get_meeting_messages(meeting["id"])) == 3
print("[PASS] Text / sign / voice / system messages stored and fetched")

import io, wave
_silent = io.BytesIO()
with wave.open(_silent, "wb") as _w:
    _w.setnchannels(1); _w.setsampwidth(2); _w.setframerate(16000); _w.writeframes(b"\x00\x00" * 16000)
stt = huggingface_service.speech_to_text(_silent.getvalue())
assert not stt["success"], "silent audio must NOT produce a transcript"
sign = huggingface_service.detect_sign_language(Image.new("RGB", (224, 224), (120, 150, 180)))
assert not sign["success"] and sign.get("unavailable"), "without a model, sign recognition must refuse (no fake signs)"
bad = huggingface_service.detect_sign_language(b"not-an-image")
assert not bad["success"]
print("[PASS] Silent audio rejected; sign recognition refuses to guess without a model; invalid image rejected")

tts_ok, tts_bytes, note = huggingface_service.text_to_speech("Test TTS audio generation.")
print(f"[{'PASS' if tts_ok else 'SKIP'}] TTS: {note}" + (f" ({len(tts_bytes)} bytes)" if tts_ok else " (gTTS needs internet)"))

assert meeting_service.leave_meeting(meeting["id"], user["id"])
assert meeting_service.end_meeting(meeting["id"])
assert meeting_service.refresh_meeting(meeting["meeting_code"])["status"] == "ended"
print("[PASS] Leave + end meeting")

print("\n=== ALL SANITY TESTS PASSED ===")
