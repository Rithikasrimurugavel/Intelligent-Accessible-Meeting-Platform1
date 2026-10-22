"""
Voice assistant brain for blind users (and anyone who prefers talking to clicking).

The browser component (components/voice_assistant) listens continuously and speaks. Every finished sentence the
person says arrives here as text; this module decides what it means, calls the real services (create account,
log in, create / join / leave meeting, send message ...) and queues what the assistant must say back.

It only needs a MutableMapping for its state (st.session_state in the app, a plain dict in tests).
"""
import re
import time
import uuid
from typing import Any, Dict, List, MutableMapping, Optional

from services.meeting_service import meeting_service
from services.message_service import message_service
from services.supabase_service import supabase_service
from services.user_service import user_service
from utils.logger import logger
from utils.speech_parse import (code_candidates, extract_meeting_title, norm, parse_email, parse_meeting_code,
                                parse_name, parse_role, parse_yes_no, speak_email, spell_code)
from utils.validation import validate_meeting_code

MAX_QUEUE = 12
MAX_ATTEMPTS = 3

_CANCEL = re.compile(r"\b(cancel|never ?mind|abort|start over|go back|forget it)\b")
_HELP = re.compile(r"\b(help|what can i say|commands|options|what can you do)\b")
_REPEAT = re.compile(r"\b(repeat|say (?:that )?again|what did you say|come again|pardon)\b")
_PAUSE = re.compile(r"\b(stop listening|pause (?:the )?(?:assistant|listening)|go to sleep|mute (?:the )?assistant)\b")
_AUDIO_ON = re.compile(r"\b(enable|turn on|switch on|start|activate)\b.*\b(audio|sound|voice guidance|announcements?|"
                       r"read ?aloud|reading)\b|\bread (?:new |incoming )?messages (?:automatically|aloud|out)\b")
_AUDIO_OFF = re.compile(r"\b(disable|turn off|switch off|stop|deactivate)\b.*\b(audio|sound|voice guidance|"
                        r"announcements?|read ?aloud|reading)\b")
_LOGOUT = re.compile(r"\b(log ?out|sign ?out|log me out)\b")
_REGISTER = re.compile(r"\b(create|make|new|register|sign ?up|open|set ?up)\b.*\b(account|profile)\b|"
                       r"\b(register|sign ?up)\b")
_LOGIN = re.compile(r"\b(log ?in|sign ?in|login)\b")
_CHANGE_ROLE = re.compile(r"\b(change|switch|set|select|choose|update)\b.*\b(role|mode)\b")
_CREATE_MEETING = re.compile(r"\b(create|start|make|new|host|set ?up)\b.*\b(meeting|room|call)\b|\bnew meeting\b")
_JOIN_MEETING = re.compile(r"\b(join|enter|attend|connect to)\b.*\b(meeting|room|call|code)?\b|\bjoin\b")
_TALK_ON = re.compile(r"\b(start|begin|enable|turn on|enter)\s+(?:talking|talk mode|speaking|dictation|live)\b|"
                      r"^(?:talk mode|let me talk|i want to talk)$")
_TALK_OFF = re.compile(r"^(?:stop|end|finish|quit|exit)\s+(?:talking|talk mode|speaking|dictation)$|"
                       r"^(?:command mode|i am done talking|i'm done talking|done talking|stop)$")
_SEND = re.compile(r"^\s*(?:please\s+)?(?:send(?: a)?(?: message)?|tell everyone|say to everyone|message everyone)"
                   r"\s*(?:that|saying|says|to everyone|:|,)?\s+(.+)$", re.I)
_READ_LAST = re.compile(r"\b(last|latest|recent|previous)\s+message\b|\bread (?:the )?last\b|\bwhat did .* say\b")
_READ_ALL = re.compile(r"\b(read|hear)\b.*\b(messages|conversation|chat|history)\b|\bwhat did i miss\b")
_PARTICIPANTS = re.compile(r"\b(who(?:'s| is) (?:here|in)|participants|attendees|who is in the meeting)\b")
_LEAVE = re.compile(r"\b(leave|exit|quit)\b.*\b(meeting|room|call)\b|^leave$")
_END = re.compile(r"\b(end|close|finish|terminate)\b.*\b(meeting|room|call)\b")
_CODE = re.compile(r"\b(meeting code|room code|what(?:'s| is) the code|repeat (?:the )?code|spell (?:the )?code|read (?:the )?code)\b")
_WHERE = re.compile(r"\b(where am i|status|what(?:'s| is) happening)\b")
_ASSISTANT = re.compile(r"^(?:assistant|computer|hey assistant)\b[\s,:.-]*(.*)$")
_LOBBY = re.compile(r"\b(lobby|continue|skip|next|proceed)\b")


_SPOKEN_ROLE = {"blind": "blind", "deaf": "deaf", "mute": "mute", "normal": "normal participant",
                "manager": "meeting host", "system": "system"}


def _role_words(role: str) -> str:
    return _SPOKEN_ROLE.get((role or "").lower(), role or "participant")


def _plausible_code(code) -> bool:
    """Meeting codes look like AM-7JWFVR. Reject plain words (e.g. 'logout') mistaken for a code."""
    return bool(code) and len(code) >= 6 and (code.startswith("AM-") or any(c.isdigit() for c in code))


def _speakable(text: str) -> str:
    """Remove emoji / symbols a speech engine would read out loud."""
    t = re.sub(r"[^\w\s.,!?'\"@:;()\-]", " ", text or "")
    return re.sub(r"\s+", " ", t).strip()


class VoiceAgent:
    def __init__(self, session: MutableMapping[str, Any]):
        self.s = session
        va = self.s.setdefault("_va", {})
        va.setdefault("sid", uuid.uuid4().hex[:10])
        va.setdefault("queue", [])
        va.setdefault("next_id", 1)
        va.setdefault("flow", None)
        va.setdefault("step", None)
        va.setdefault("data", {})
        va.setdefault("attempts", 0)
        va.setdefault("last_prompt", "")
        va.setdefault("greeted", False)
        va.setdefault("talk_mode", False)
        va.setdefault("auto_read", True)
        va.setdefault("paused", False)
        va.setdefault("last_event", None)
        va.setdefault("seen_for", None)
        va.setdefault("seen_ids", [])
        self.va = va
        self.navigate = False

    # ------------------------------------------------------------------ plumbing
    def say(self, text: str, remember: bool = True):
        text = _speakable(text)
        if not text:
            return
        q: List[Dict[str, Any]] = self.va["queue"]
        q.append({"id": self.va["next_id"], "text": text})
        self.va["next_id"] += 1
        del q[:-MAX_QUEUE]
        if remember:
            self.va["last_prompt"] = text

    def beep(self):
        self.va["queue"].append({"id": self.va["next_id"], "beep": True})
        self.va["next_id"] += 1
        del self.va["queue"][:-MAX_QUEUE]

    def queue_signature(self) -> int:
        return self.va["next_id"]

    @property
    def user(self) -> Optional[Dict[str, Any]]:
        return self.s.get("user")

    @property
    def meeting(self) -> Optional[Dict[str, Any]]:
        return self.s.get("current_meeting")

    def context(self) -> str:
        if not self.user:
            return "logged_out"
        m = self.meeting
        if m and m.get("status") != "ended":
            return "meeting"
        if self.s.get("current_page") == "role_selection":
            return "roles"
        return "lobby"

    def _start_flow(self, flow: str, step: str, prompt: str, data: Optional[dict] = None):
        self.va.update(flow=flow, step=step, data=data or {}, attempts=0)
        self.say(prompt)

    def _end_flow(self):
        self.va.update(flow=None, step=None, data={}, attempts=0)

    def _goto(self, page: str):
        self.s["current_page"] = page
        self.navigate = True

    # ------------------------------------------------------------------ greetings
    def greet_if_needed(self):
        if self.va["greeted"]:
            return
        self.va["greeted"] = True
        self.say("Voice assistant ready. " + self._help_text(short=True))

    def _help_text(self, short: bool = False) -> str:
        ctx = self.context()
        if ctx == "logged_out":
            return ("You can say: create account, or log in. Say help at any time, repeat to hear me again, "
                    "or cancel to stop what we are doing.") if short else (
                "Say create account to register with your voice. Say log in if you already have an account. "
                "Say repeat to hear the last thing again. Say cancel to stop. Say stop listening to pause me.")
        if ctx == "roles":
            return ("Say your role: blind, deaf, mute, normal, or host. Or say continue to keep your current role.")
        if ctx == "lobby":
            return ("You are in the lobby. Say create meeting, followed by a title, to host a meeting. "
                    "Say join meeting to enter one with a code. Say change role, or log out. "
                    "Say enable audio or disable audio to control spoken announcements.")
        return ("You are in a meeting. Say start talking, and everything you say is sent to the meeting, "
                "until you say stop talking. Or say send message, followed by your message. "
                "Say read last message, read messages, who is here, meeting code, leave meeting, "
                "enable audio, or disable audio. While talking, begin with the word assistant to give a command.")

    # ------------------------------------------------------------------ main entry
    def handle(self, text: str, confidence: Optional[float] = None) -> None:
        text = (text or "").strip()
        if not text:
            return
        n = norm(text)
        logger.info(f"Voice heard: '{text}' (ctx={self.context()}, flow={self.va['flow']})")

        # Talk mode: everything is a chat message, except explicit assistant commands.
        if self.context() == "meeting" and self.va["talk_mode"] and not self.va["flow"]:
            m = _ASSISTANT.match(n)
            if m:
                if not m.group(1):
                    self.say("Yes?", remember=False)
                    return
                text, n = m.group(1), norm(m.group(1))
            elif _TALK_OFF.search(n):
                self.va["talk_mode"] = False
                self.say("Command mode. I will no longer send what you say. Say help for commands.")
                return
            else:
                self._send_to_meeting(text, confidence)
                return

        # Active dialogue (account creation, joining ...)
        if self.va["flow"]:
            if _CANCEL.search(n):
                self._end_flow()
                self.say("Cancelled. " + self._help_text(short=True))
            elif _HELP.search(n):
                self.say("I am waiting for your answer. " + self.va["last_prompt"], remember=False)
            elif _REPEAT.search(n):
                self.say(self.va["last_prompt"], remember=False)
            else:
                self._continue_flow(text, n)
            return

        # Global commands
        if _REPEAT.search(n) and not _CODE.search(n) and self.va["last_prompt"]:
            self.say(self.va["last_prompt"], remember=False)
        elif _HELP.search(n):
            self.say(self._help_text())
        elif _PAUSE.search(n):
            self.va["paused"] = True
            self.say("Listening paused. Press the voice assistant button or the space bar to resume.", remember=False)
        elif _AUDIO_OFF.search(n):
            self.va["auto_read"] = False
            self.s["voice_guidance_enabled"] = False
            self.say("Audio announcements disabled. I will only speak when you ask me something.")
        elif _AUDIO_ON.search(n):
            self.va["auto_read"] = True
            self.s["voice_guidance_enabled"] = True
            self.say("Audio enabled. I will read new meeting messages and announcements aloud.")
        elif _WHERE.search(n):
            self._say_where()
        elif _LOGOUT.search(n) and self.user:
            self._logout()
        else:
            ctx = self.context()
            handled = {"logged_out": self._ctx_logged_out, "roles": self._ctx_roles,
                       "lobby": self._ctx_lobby, "meeting": self._ctx_meeting}[ctx](text, n)
            if not handled:
                self.say("Sorry, I did not understand. " + (
                    "Say start talking to speak to everyone, or say help." if ctx == "meeting"
                    else "Say help to hear what you can do."))

    # ------------------------------------------------------------------ contexts
    def _ctx_logged_out(self, text: str, n: str) -> bool:
        if _REGISTER.search(n):
            self._start_flow("register", "name", "Let's create your account. What is your full name?")
            return True
        if _LOGIN.search(n):
            self._start_flow("login", "email",
                             "Okay, let's log you in. Please say your email address, for example: "
                             "john dot smith at gmail dot com.")
            return True
        return False

    def _ctx_roles(self, text: str, n: str) -> bool:
        role = parse_role(n)
        if role:
            return self._apply_role(role)
        if _LOBBY.search(n):
            self._goto("meeting_room")
            self.say("Okay. You are in the lobby. " + self._help_text(short=False))
            return True
        return False

    def _ctx_lobby(self, text: str, n: str) -> bool:
        if _CHANGE_ROLE.search(n):
            self._start_flow("role", "role", "Which role do you want? Say blind, deaf, mute, normal, or host.")
            return True
        if _CREATE_MEETING.search(n):
            title = extract_meeting_title(text)
            if title:
                self._create_meeting(title)
            else:
                self._start_flow("create_meeting", "title", "What should the meeting be called?")
            return True
        if _JOIN_MEETING.search(n):
            code = parse_meeting_code(re.sub(r"\b(join|enter|attend|connect to|meeting|call|room)\b", " ", n))
            if _plausible_code(code) and validate_meeting_code(code):
                self._join_meeting(code)
            else:
                self._start_flow("join_meeting", "code",
                                 "Please say the meeting code, letter by letter. For example: A, M, dash, eight, F, "
                                 "three, K, nine, two.")
            return True
        role = parse_role(n)
        if role and re.search(r"\b(i am|i'm|role)\b", n):
            return self._apply_role(role)
        return False

    def _ctx_meeting(self, text: str, n: str) -> bool:
        m = _SEND.match(text)
        if m and len(m.group(1).strip()) >= 1:
            self._send_to_meeting(m.group(1).strip(), None, announce=True)
            return True
        if _TALK_ON.search(n):
            self.va["talk_mode"] = True
            self.say("Talk mode on. Everything you say will be sent to the meeting. "
                     "Say stop talking when you are done. Start a command with the word assistant.")
            return True
        if _TALK_OFF.search(n):
            self.say("You are already in command mode.", remember=False)
            return True
        if _READ_LAST.search(n):
            self._read_messages(1)
            return True
        if _READ_ALL.search(n):
            self._read_messages(5)
            return True
        if _PARTICIPANTS.search(n):
            self._say_participants()
            return True
        if _CODE.search(n):
            self.say(f"The meeting code is {spell_code(self.meeting['meeting_code'])}.")
            return True
        if _LEAVE.search(n):
            self._leave_meeting()
            return True
        if _END.search(n):
            self._start_end_meeting()
            return True
        return False

    # ------------------------------------------------------------------ dialogue steps
    def _continue_flow(self, text: str, n: str):
        flow, step, d = self.va["flow"], self.va["step"], self.va["data"]

        if flow in ("register", "login") and step == "name":
            name = parse_name(text)
            if not name:
                return self._retry("I did not catch your name. Please say your full name.")
            d["name"] = name
            self.va.update(step="email", attempts=0)
            return self.say(f"Nice to meet you, {name}. Now say your email address, for example: "
                            "john dot smith at gmail dot com. You can also spell it letter by letter.")

        if step == "email":
            email = parse_email(text)
            if not email:
                return self._retry("I could not understand that email address. Please say it again, like: "
                                   "john dot smith at gmail dot com.")
            d["email"] = email
            self.va.update(step="email_confirm", attempts=0)
            return self.say(f"I heard: {speak_email(email)}. Is that correct? Say yes or no.")

        if step == "email_confirm":
            yn = parse_yes_no(text)
            if yn is None:
                return self.say("Please say yes or no. " + f"Your email is {speak_email(d['email'])}.")
            if not yn:
                self.va.update(step="email", attempts=0)
                return self.say("Okay, please say your email address again.")
            if flow == "register":
                self.va.update(step="role", attempts=0)
                return self.say("Thank you. Now choose your role. Say blind if you are visually impaired, deaf, "
                                "mute, normal, or host.")
            return self._finish_login(d["email"])

        if flow == "register" and step == "role":
            role = parse_role(n)
            if not role:
                return self._retry("I did not catch the role. Say blind, deaf, mute, normal, or host.")
            return self._finish_register(d["name"], d["email"], role)

        if flow == "role" and step == "role":
            role = parse_role(n)
            if not role:
                return self._retry("I did not catch the role. Say blind, deaf, mute, normal, or host.")
            self._end_flow()
            self._apply_role(role)
            return

        if flow == "create_meeting" and step == "title":
            title = extract_meeting_title(text) or (text.strip().title() if len(text.strip()) >= 3 else None)
            if not title:
                return self._retry("The title needs at least three letters. What should the meeting be called?")
            self._end_flow()
            return self._create_meeting(title)

        if flow == "join_meeting" and step == "code":
            code = parse_meeting_code(text)
            if not _plausible_code(code):
                return self._retry("I could not understand the code. Please say it letter by letter, "
                                   "for example: A, M, dash, eight, F, three, K, nine, two.")
            if self._join_meeting(code, from_flow=True):
                self._end_flow()
            else:
                self._retry(None)
            return

        if flow == "end_meeting" and step == "confirm":
            yn = parse_yes_no(text)
            if yn is None:
                return self.say("Please say yes to end the meeting for everyone, or no to keep it running.")
            self._end_flow()
            if not yn:
                return self.say("Okay, the meeting continues.")
            return self._do_end_meeting()

        self._end_flow()
        self.say("Sorry, I lost track. " + self._help_text(short=True))

    def _retry(self, prompt: Optional[str]):
        self.va["attempts"] += 1
        if self.va["attempts"] >= MAX_ATTEMPTS:
            self._end_flow()
            return self.say("I am having trouble understanding. Let's stop for now. " + self._help_text(short=True))
        if prompt:
            self.say(prompt)

    # ------------------------------------------------------------------ actions
    def _set_user(self, profile: Dict[str, Any]):
        self.s["user"] = profile
        self.s["voice_mode"] = True
        self.s["current_meeting"] = None
        self._goto("meeting_room")

    def _finish_register(self, name: str, email: str, role: str):
        existing = None
        try:
            existing = supabase_service.get_user_by_email(email)
        except Exception:
            pass
        ok, profile, msg = user_service.register_user(name=name, email=email, role=role)
        if not ok or not profile:
            self.va.update(step="email", attempts=0)
            return self.say(f"Sorry, I could not create the account. {msg} Please say your email address again.")
        self._end_flow()
        self._set_user(profile)
        prefix = "I found your existing account and updated it. " if existing else "Your account is ready. "
        self.say(f"{prefix}Welcome, {name}. Your role is {_role_words(role)}. "
                 "You are now in the meeting lobby. Say create meeting to host a meeting, or join meeting to enter one.")

    def _finish_login(self, email: str):
        try:
            profile = supabase_service.get_user_by_email(email)
        except Exception as e:
            logger.error(f"voice login lookup error: {e}")
            self._end_flow()
            return self.say(f"Sorry, I could not reach the account database. {e}")
        self._end_flow()
        if not profile:
            return self.say("I could not find an account with that email. Say create account to register, "
                            "or say log in to try another email.")
        self._set_user(profile)
        self.say(f"Welcome back, {profile['name']}. Your role is {_role_words(profile['role'])}. "
                 "You are in the meeting lobby. Say create meeting, join meeting, or change role.")

    def _apply_role(self, role: str) -> bool:
        ok, profile, msg = user_service.update_role(self.user, role)
        if not ok:
            self.say(f"Sorry, I could not change your role. {msg}")
            return True
        self.s["user"] = profile
        self._goto("meeting_room")
        self.say(f"Role set to {_role_words(role)}. You are in the lobby. "
                 "Say create meeting or join meeting.")
        return True

    def _create_meeting(self, title: str):
        user = self.user
        ok, m, msg = meeting_service.create_meeting(title=title, host_id=user["id"])
        if not ok or not m:
            return self.say(f"Sorry, I could not create the meeting. {msg}")
        meeting_service.join_meeting(m["meeting_code"], user["id"], user["role"])
        message_service.send_system_message(m["id"], f"Meeting '{m['title']}' started by {user['name']}.")
        self._enter(m)
        self.say(f"Meeting {m['title']} created and started. The meeting code is {spell_code(m['meeting_code'])}. "
                 "Say meeting code to hear it again. Say start talking to speak to the meeting, or say help.")

    def _join_meeting(self, code: str, from_flow: bool = False) -> bool:
        user = self.user
        last_msg = ""
        for cand in code_candidates(code):
            if not validate_meeting_code(cand):
                continue
            ok, m, _p, msg = meeting_service.join_meeting(cand, user["id"], user["role"])
            if ok and m:
                message_service.send_system_message(m["id"], f"{user['name']} joined the meeting as {user['role']}.")
                self._enter(m)
                n = len(meeting_service.get_participants(m["id"]))
                self.say(f"You joined {m['title']}. There {'is' if n == 1 else 'are'} {n} "
                         f"participant{'s' if n != 1 else ''} here. Say start talking to speak, or say help.")
                return True
            last_msg = last_msg or msg
            if "ended" in msg:
                break
        self.say(f"I could not join with the code {spell_code(code)}. {last_msg} "
                 + ("Please say the code again, or say cancel." if from_flow else ""))
        return False

    def _enter(self, meeting: Dict[str, Any]):
        self.s["current_meeting"] = meeting
        self.va["talk_mode"] = False
        self._mark_all_seen(meeting)
        self._goto("meeting_room")

    def _leave_meeting(self):
        m, u = self.meeting, self.user
        meeting_service.leave_meeting(m["id"], u["id"])
        message_service.send_system_message(m["id"], f"{u['name']} left the meeting.")
        self.s["current_meeting"] = None
        self.va["talk_mode"] = False
        self._goto("meeting_room")
        self.say("You left the meeting. You are back in the lobby. Say create meeting or join meeting.")

    def _start_end_meeting(self):
        if str(self.meeting.get("host_id")) != str(self.user["id"]):
            return self.say("Only the host can end the meeting for everyone. Say leave meeting to leave.")
        self._start_flow("end_meeting", "confirm", "Do you want to end the meeting for everyone? Say yes or no.")

    def _do_end_meeting(self):
        m = self.meeting
        message_service.send_system_message(m["id"], "The host ended the meeting.")
        if meeting_service.end_meeting(m["id"]):
            self.s["current_meeting"] = None
            self._goto("meeting_room")
            self.say("The meeting has ended for everyone. You are back in the lobby.")
        else:
            self.say("Sorry, I could not end the meeting.")

    def _logout(self):
        keep = {k: self.s[k] for k in ("_va", "voice_mode") if k in self.s}
        for k in list(self.s.keys()):
            del self.s[k]
        self.s.update(keep)
        self.va.update(flow=None, step=None, data={}, talk_mode=False, seen_for=None)
        self.s["current_page"] = "login"
        self.s["user"] = None
        self.s["current_meeting"] = None
        self.navigate = True
        self.say("You are logged out. Say create account, or log in.")

    def _say_where(self):
        ctx = self.context()
        if ctx == "logged_out":
            return self.say("You are on the login page. Say create account, or log in.")
        name = self.user["name"]
        if ctx == "meeting":
            return self.say(f"{name}, you are in the meeting {self.meeting['title']}. "
                            f"{'Talk mode is on.' if self.va['talk_mode'] else 'Command mode is on.'}")
        return self.say(f"{name}, you are in the lobby. Say create meeting or join meeting.")

    # ------------------------------------------------------------------ meeting helpers
    def _send_to_meeting(self, text: str, confidence: Optional[float], announce: bool = False):
        m, u = self.meeting, self.user
        ok, _msg, status = message_service.send_voice_text_message(
            m["id"], u["id"], u["name"], u["role"], text, confidence)
        if ok:
            self._remember_own(_msg)
            if announce:
                self.say("Message sent.", remember=False)
            else:
                self.beep()
        else:
            self.say(f"Sorry, the message was not sent. {status}")

    def _visible_messages(self) -> List[Dict[str, Any]]:
        return [x for x in message_service.get_meeting_messages(self.meeting["id"])
                if x.get("input_type") != "system"]

    def _read_messages(self, count: int):
        msgs = self._visible_messages()[-count:]
        if not msgs:
            return self.say("There are no messages yet.")
        self.say(" ".join(f"{x.get('sender_name', 'Someone')} said: {x.get('text_content', '')}." for x in msgs))

    def _say_participants(self):
        people = meeting_service.get_participants(self.meeting["id"])
        if not people:
            return self.say("I could not find any participants.")
        self.say(f"{len(people)} participant{'s' if len(people) != 1 else ''} here: " + ", ".join(
            f"{p.get('name', 'Participant')}, {_role_words(p.get('role', 'normal'))}" for p in people) + ".")

    # ------------------------------------------------------------------ incoming announcements
    def _mark_all_seen(self, meeting: Dict[str, Any]):
        ids = [x["id"] for x in message_service.get_meeting_messages(meeting["id"]) if x.get("id")]
        self.va["seen_for"] = meeting["id"]
        self.va["seen_ids"] = ids[-500:]

    def _remember_own(self, msg: Optional[Dict[str, Any]]):
        if msg and msg.get("id"):
            self.va["seen_ids"].append(msg["id"])

    def poll_incoming(self):
        """Announce NEW meeting messages and detect that the host ended the meeting. Called every few seconds."""
        if self.context() != "meeting":
            return
        m = self.meeting
        if self.va["seen_for"] != m["id"]:
            self._mark_all_seen(m)
            return
        fresh = meeting_service.refresh_meeting(m["meeting_code"])
        if fresh and fresh.get("status") == "ended":
            self.s["current_meeting"] = None
            self.va["talk_mode"] = False
            self._goto("meeting_room")
            self.say("The host ended the meeting. You are back in the lobby. Say create meeting or join meeting.")
            return
        seen = set(self.va["seen_ids"])
        me = str(self.user["id"])
        for msg in message_service.get_meeting_messages(m["id"]):
            mid = msg.get("id")
            if not mid or mid in seen:
                continue
            self.va["seen_ids"].append(mid)
            if not self.va["auto_read"] or str(msg.get("sender_id")) == me:
                continue
            body = msg.get("text_content", "")
            if msg.get("input_type") == "system":
                self.say(body, remember=False)
            else:
                self.say(f"{msg.get('sender_name', 'Someone')} says: {body}", remember=False)
        del self.va["seen_ids"][:-500]
