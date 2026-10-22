"""
Turns what a blind user SAYS into structured intents / clean values.

Pure functions only (no Streamlit, no database) so they are easy to unit-test.
"""
import re
from dataclasses import dataclass
from typing import Optional

from utils.validation import validate_meeting_code

_DIGITS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
           "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
_NATO = {w: w[0] for w in (
    "alpha alfa bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike "
    "november oscar papa quebec romeo sierra tango uniform victor whiskey xray yankee zulu").split()}
_SYMBOLS = {"dash": "-", "hyphen": "-", "minus": "-", "underscore": "_", "plus": "+", "dot": ".", "period": ".",
            "point": "."}
_FILLER_CODE = {"the", "code", "meeting", "number", "is", "its", "it's", "id", "um", "uh", "please", "my"}
_ROLE_WORDS = [
    ("blind", ("blind", "visually impaired", "visual impairment", "low vision")),
    ("manager", ("host", "manager", "organizer", "organiser")),
    ("deaf", ("deaf", "hearing impaired", "hard of hearing")),
    ("mute", ("mute", "speech impaired", "sign language", "cannot speak", "can't speak")),
    ("normal", ("normal", "regular", "standard", "participant")),
]


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_for_matching(text: str) -> str:
    """Lower-case, strip punctuation (keep apostrophes) so regexes are simple."""
    t = clean_text(text).lower()
    return re.sub(r"[^\w\s'@.-]", " ", t).replace("  ", " ").strip()


# --------------------------------------------------------------------------- values
def extract_name(spoken: str) -> str:
    t = clean_text(spoken)
    t = re.sub(r"^(?:hi|hello|hey)[, ]+", "", t, flags=re.I)
    t = re.sub(r"^(?:my name is|my name's|i am|i'm|it is|it's|this is|call me|name is)\s+", "", t, flags=re.I)
    t = re.sub(r"[^A-Za-z\u00C0-\u024F .'-]", "", t).strip(" .")
    return " ".join(w.capitalize() if w.islower() else w for w in t.split())


def normalize_email(spoken: str) -> str:
    """'john dot smith at gmail dot com' -> 'john.smith@gmail.com'."""
    t = clean_text(spoken).lower()
    t = re.sub(r"\bat the rate( of)?\b", " @ ", t)
    t = re.sub(r"\bat sign\b", " @ ", t)
    t = re.sub(r"[,?!]", " ", t)
    out = []
    for tok in t.split():
        if tok == "at":
            out.append("@")
        elif tok in _SYMBOLS:
            out.append(_SYMBOLS[tok])
        elif tok in _DIGITS:
            out.append(_DIGITS[tok])
        elif tok in _NATO:
            out.append(_NATO[tok])
        else:
            out.append(tok)
    email = "".join(out).strip(".")
    email = re.sub(r"\.{2,}", ".", email)
    # Recognisers sometimes append a sentence-ending period or write "g mail".
    email = email.replace("@@", "@")
    return email


def normalize_meeting_code(spoken: str) -> str:
    """'A M dash 8 F 3 K nine 2' -> 'AM-8F3K92'."""
    t = re.sub(r"[,?!]", " ", clean_text(spoken).lower())
    toks = [x for x in t.split() if x not in _FILLER_CODE]
    out = []
    for tok in toks:
        if tok in _DIGITS:
            out.append(_DIGITS[tok])
        elif tok in _NATO:
            out.append(_NATO[tok])
        elif tok in ("dash", "hyphen", "minus"):
            out.append("-")
        else:
            out.append(tok)
    code = re.sub(r"[^A-Za-z0-9-]", "", "".join(out)).upper()
    if code.startswith("AM") and not code.startswith("AM-") and len(code) > 2:
        code = "AM-" + code[2:]
    return code


def spell_out(value: str) -> str:
    """'AM-8F3K92' -> 'A, M, dash, 8, F, 3, K, 9, 2' (for the speech engine)."""
    names = {"-": "dash", "@": "at", ".": "dot", "_": "underscore", "+": "plus"}
    return ", ".join(names.get(c, c) for c in value)


def is_yes(text: str) -> bool:
    return bool(re.search(r"\b(yes|yeah|yep|yup|correct|right|confirm|confirmed|sure|okay|ok|affirmative|go ahead)\b",
                          normalize_for_matching(text)))


def is_no(text: str) -> bool:
    return bool(re.search(r"\b(no|nope|nah|wrong|incorrect|negative|not correct|not right)\b",
                          normalize_for_matching(text)))


def detect_role(text: str) -> Optional[str]:
    t = normalize_for_matching(text)
    for role, words in _ROLE_WORDS:
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
            return role
    return None


# --------------------------------------------------------------------------- intents
@dataclass
class Intent:
    name: str
    value: str = ""


_NOUNS_AUDIO = (r"(?:audio|voice guidance|guidance|sound|announcements?|read ?aloud|speech|"
                r"voice assistant|voice feedback|narration)")


def parse_intent(spoken: str) -> Intent:
    """Map one utterance to an Intent. Unknown speech -> Intent('unknown')."""
    raw = clean_text(spoken)
    t = normalize_for_matching(spoken)
    if not t:
        return Intent("unknown")

    if re.search(r"\b(cancel|never ?mind|start over|forget it|go back)\b", t):
        return Intent("cancel")
    if re.search(r"\b(repeat that|say that again|repeat please|what did you say|come again|repeat)\b", t) \
            and not re.search(r"\b(message|send)\b", t):
        return Intent("repeat")

    # audio / guidance toggles (before generic "start"/"stop" matches)
    if re.search(rf"\b(enable|turn on|switch on|activate|unmute|resume)\b.*\b{_NOUNS_AUDIO}\b", t) \
            or re.search(rf"\b{_NOUNS_AUDIO}\b.*\b(on|enable|enabled)\b$", t):
        return Intent("guidance_on")
    if re.search(rf"\b(disable|turn off|switch off|deactivate|mute|silence|stop)\b.*\b{_NOUNS_AUDIO}\b", t) \
            or re.search(rf"\b{_NOUNS_AUDIO}\b.*\b(off|disable|disabled)\b$", t):
        return Intent("guidance_off")

    if re.search(r"\b(stop|pause|turn off) dictation\b", t) or "dictation off" in t:
        return Intent("dictation_off")
    if re.search(r"\b(start|resume|turn on|enable) dictation\b", t) or "dictation on" in t:
        return Intent("dictation_on")

    if re.search(r"\b(log ?out|sign ?out|log me out)\b", t):
        return Intent("logout")
    if re.search(r"\b(create|make|new|register|open)\b.*\b(account|profile)\b|\bsign ?up\b|\bregister\b", t):
        return Intent("create_account")
    if re.search(r"\b(log ?in|sign ?in|login)\b", t):
        return Intent("login")

    if re.search(r"\b(set|change|switch|select|choose|make)\b.*\b(role|me|myself)\b", t) \
            or re.search(r"\b(i am|i'm|i'm a|role is)\b", t) and detect_role(t):
        role = detect_role(t)
        if role:
            return Intent("set_role", role)

    if re.search(r"\b(end|close|finish|terminate)\b.*\bmeeting\b", t):
        return Intent("end_meeting")
    if re.search(r"\b(leave|exit|quit)\b", t) and not re.search(r"\bmessage\b", t):
        return Intent("leave_meeting")

    if re.search(r"\b(create|start|host|new|make|begin|schedule)\b.*\bmeeting\b", t):
        m = re.search(r"\b(?:titled|called|named|title is|title|name is|name)\s+(.+)$", raw, flags=re.I)
        return Intent("create_meeting", clean_text(m.group(1)).strip(" .") if m else "")
    if re.search(r"\bjoin\b", t):
        m = re.search(r"\bjoin\b(?:\s+(?:the|a|my))?(?:\s+meeting)?(?:\s+(?:with|using))?(?:\s+(?:code|number|id))?\s*(.*)$",
                      raw, flags=re.I)
        return Intent("join_meeting", clean_text(m.group(1)) if m else "")

    if re.search(r"\b(what'?s|what is|tell me|say|read)\b.*\b(meeting )?code\b", t):
        return Intent("meeting_code")
    if re.search(r"\b(who is|who's|list|how many)\b.*\b(here|meeting|participants?|present|attending)\b|\bparticipants\b", t):
        return Intent("participants")
    if re.search(r"\b(read|play|what (?:did|are|were)|any new|latest|last|recent)\b.*\b(messages?|chat|said|say)\b", t) \
            or re.search(r"\bread (?:it|them|back)\b", t):
        return Intent("read_messages", "all" if re.search(r"\b(all|everything|history)\b", t) else "")
    m = re.match(r"^(?:please\s+)?(?:send|broadcast|tell everyone|tell them|message|post)(?:\s+(?:a\s+)?message)?"
                 r"(?:\s+(?:that|saying|to everyone))?[:,]?\s+(.+)$", raw, flags=re.I)
    if m:
        return Intent("send_message", clean_text(m.group(1)))

    if re.search(r"\b(where am i|what page|status|what can i do now)\b", t):
        return Intent("status")
    if re.search(r"\b(help|what can i say|what can i do|commands|options|instructions)\b", t):
        return Intent("help")
    return Intent("unknown", raw)
