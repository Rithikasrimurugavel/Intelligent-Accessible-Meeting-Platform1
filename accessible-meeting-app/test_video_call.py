"""Tests for the live video meeting's server side (signalling + event handling). Run: python test_video_call.py"""
import time
from components.video_call import call_config, process_batch
from services.call_service import call_service, PEER_TTL_SECONDS
from services.meeting_service import meeting_service
from services.message_service import message_service
from services.user_service import user_service

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("[PASS] " if cond else "[FAIL] ") + name)

# role configuration
check("blind: audio only, no camera, no video tiles", call_config("blind") == {**call_config("blind"), "cam": False, "mic": True, "show_video": False})
check("mute: camera + sign reading, no microphone", call_config("mute")["cam"] and call_config("mute")["sign"] and not call_config("mute")["mic"])
check("normal/manager: camera + mic + speech subtitles", all(call_config(r)["cam"] and call_config(r)["mic"] and call_config(r)["speech"] for r in ("normal", "manager")))
check("speech subtitles off for every role while the voice assistant is on", not any(call_config(r, voice_mode=True)["speech"] for r in ("blind", "normal", "manager")) and call_config("blind")["speech"])

# signalling: only present peers can talk, messages are addressed and expire
R = "room-test"
check("heartbeat registers peers", call_service.heartbeat(R, "A", "u1", "Ann", "normal") and call_service.heartbeat(R, "B", "u2", "Bo", "mute"))
check("peers() excludes me", [p["sid"] for p in call_service.peers(R, "A")] == ["B"])
check("push only to a present peer", call_service.push(R, "A", "B", {"type": "offer", "sdp": "x"}) and not call_service.push(R, "A", "ghost", {"type": "offer"}))
check("only the addressee gets the signal", len(call_service.inbox(R, "B")) == 1 and call_service.inbox(R, "A") == [])
check("oversized signal rejected", not call_service.push(R, "A", "B", {"sdp": "x" * 200_000}))
call_service.leave(R, uid="u2"); check("leave removes the peer", call_service.peers(R, "A") == [])
call_service.leave(R, sid="A")

# event batches from the browser -> signalling, chat log, sign handler
okh, host, _ = user_service.register_user(name="Hosty", email=f"hosty{int(time.time())}@example.com", role="manager")
ok_c, m, _msg = meeting_service.create_meeting(title="Test", host_id=host["id"])
mid = m["id"]; user = {"id": "u-vid", "name": "Vid", "role": "normal"}
got = []
n = process_batch(mid, user, {"id": "b1", "sid": "S1", "events": [
    {"t": "hello"}, {"t": "caption", "text": "  good morning everyone ", "conf": 0.9},
    {"t": "sign", "words": ["hello", "you"], "conf": 0.8}, {"t": "bogus"}, "junk", {"t": "caption", "text": "   "}]}, got.append)
check("batch handled: hello + caption + sign (junk ignored)", n == 3)
check("hello registered the browser in the call", [p["sid"] for p in call_service.peers(mid)] == ["S1"])
check("sign sentence forwarded to the handler", got == [{"words": ["hello", "you"], "conf": 0.8}])
texts = [x.get("text_content") for x in message_service.get_meeting_messages(mid)]
check("spoken caption saved to the meeting conversation", "good morning everyone" in texts)
check("batch without a session id is refused", process_batch(mid, user, {"id": "b2", "events": [{"t": "hello"}]}, got.append) == 0)
print("\n=== ALL VIDEO CALL TESTS PASSED ===" if ok else "\n=== SOME TESTS FAILED ==="); raise SystemExit(0 if ok else 1)
