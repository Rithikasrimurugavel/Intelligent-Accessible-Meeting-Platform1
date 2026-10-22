"""
Turn what a person SAYS into structured values (names, e-mails, meeting codes, roles, yes/no).
Pure functions - no Streamlit, no network - so they can be unit-tested.
"""
import re
from itertools import product
from typing import List, Optional

_DIGITS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
           "six": "6", "seven": "7", "eight": "8", "nine": "9", "won": "1", "to": "2", "too": "2",
           "for": "4", "ate": "8"}
_NATO = {w: w[0].upper() for w in (
    "alpha alfa bravo charlie delta echo foxtrot golf hotel india juliet juliett kilo lima mike november oscar papa "
    "quebec romeo sierra tango uniform victor whiskey xray yankee zulu").split()}
_NATO["x-ray"] = "X"
_LETTER_SOUNDS = {"bee": "B", "be": "B", "see": "C", "sea": "C", "dee": "D", "gee": "G", "jay": "J", "kay": "K",
                  "el": "L", "em": "M", "en": "N", "oh": "O", "pea": "P", "pee": "P", "cue": "Q", "queue": "Q",
                  "are": "R", "ess": "S", "tee": "T", "tea": "T", "you": "U", "vee": "V", "ex": "X",
                  "why": "Y", "zed": "Z", "zee": "Z", "eye": "I", "aye": "A"}

YES_WORDS = {"yes", "yeah", "yep", "yup", "correct", "right", "confirm", "confirmed", "sure", "ok", "okay",
             "affirmative", "absolutely", "definitely", "please", "do it", "go ahead", "that is correct",
             "that's correct", "that's right", "that is right"}
NO_WORDS = {"no", "nope", "nah", "wrong", "incorrect", "negative", "not correct", "not right", "that's wrong",
            "that is wrong", "again", "retry", "redo"}

ROLE_KEYWORDS = [
    ("blind", ("blind", "visually", "visual", "low vision", "can't see", "cannot see", "screen reader")),
    ("deaf", ("deaf", "hearing", "hard of hearing", "can't hear", "cannot hear")),
    ("mute", ("mute", "speech", "sign language", "sign", "can't speak", "cannot speak", "non verbal", "nonverbal")),
    ("manager", ("host", "manager", "organizer", "organiser", "admin", "teacher", "leader")),
    ("normal", ("normal", "regular", "standard", "participant", "ordinary", "attendee", "guest", "default")),
]

_COMMON_DOMAINS = ("gmail", "yahoo", "outlook", "hotmail", "icloud", "proton", "protonmail", "live", "rediffmail")


def norm(text: str) -> str:
    """Lower-case, strip punctuation, collapse spaces (keeps apostrophes and hyphens)."""
    t = re.sub(r"[^\w\s'-]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def parse_yes_no(text: str) -> Optional[bool]:
    n = norm(text)
    if not n:
        return None
    if n in NO_WORDS or re.search(r"\b(no|nope|wrong|incorrect|not)\b", n):
        return False
    if n in YES_WORDS or re.search(r"\b(yes|yeah|yep|yup|correct|right|confirm|sure|okay|ok)\b", n):
        return True
    return None


def parse_role(text: str) -> Optional[str]:
    n = norm(text)
    for role, words in ROLE_KEYWORDS:
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", n):
                return role
    return None


def parse_name(text: str) -> Optional[str]:
    t = re.sub(r"^\s*(?:hi|hello|hey)[,\s]+", "", text or "", flags=re.I)
    t = re.sub(r"^\s*(?:my name is|my name's|i am|i'm|im|this is|it is|it's|its|call me|name is|the name is)\s+",
               "", t, flags=re.I)
    t = re.sub(r"[,\s]*(?:please|thanks|thank you)\s*$", "", t, flags=re.I)
    t = re.sub(r"[^A-Za-z .'\-]", "", t).strip(" .")
    if len(t) < 2 or len(t) > 60:
        return None
    return " ".join(w.capitalize() for w in t.split())


def parse_email(text: str) -> Optional[str]:
    """'john dot smith at gmail dot com' / 'j o h n at gmail dot com' -> 'john.smith@gmail.com'."""
    t = (text or "").lower()
    t = re.sub(r"\b(my )?(e-?mail( address| id)?|address|is|it's|its)\b", " ", t)
    t = re.sub(r"\bat the rate( of)?\b|\bat sign\b|\bat symbol\b", " @ ", t)
    t = re.sub(r"\bat\b", " @ ", t)
    t = re.sub(r"\b(dot|period|point|full stop)\b", " . ", t)
    t = re.sub(r"\b(underscore|under score)\b", " _ ", t)
    t = re.sub(r"\b(dash|hyphen|minus)\b", " - ", t)
    t = re.sub(r"\bplus\b", " + ", t)
    toks = re.findall(r"[a-z0-9]+|[@._+\-]", t)
    out = []
    for tok in toks:
        out.append(_DIGITS[tok] if tok in _DIGITS and tok not in ("to", "too", "for", "ate", "won") else tok)
    email = "".join(out)
    email = re.sub(r"\.{2,}", ".", email).strip(".")
    if email.count("@") != 1:
        return None
    local, domain = email.split("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        return None
    return email if re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", email) else None


def speak_email(email: str) -> str:
    """How the assistant reads an e-mail back: local part spelled out, well-known domains as words."""
    local, domain = email.split("@")
    spelled = ", ".join(_say_char(c) for c in local)
    name, _, rest = domain.partition(".")
    dom = name if name in _COMMON_DOMAINS else ", ".join(_say_char(c) for c in name)
    return f"{spelled}, at, {dom}, dot, {rest.replace('.', ', dot, ')}"


def _say_char(c: str) -> str:
    return {".": "dot", "_": "underscore", "-": "dash", "+": "plus", "@": "at"}.get(c, c)


_CODE_NOISE = re.compile(r"\b(the|my|meeting|code|is|it's|its|join|please|number|id|room|with|using|that)\b")


def parse_meeting_code(text: str) -> Optional[str]:
    """'A M dash eight F three K nine two' / 'am 8f3k92' -> 'AM-8F3K92'."""
    t = _CODE_NOISE.sub(" ", (text or "").lower())
    toks = re.findall(r"[a-z0-9]+|-", t)
    out: List[str] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok == "double" and i + 1 < len(toks):
            nxt = _tok_to_chars(toks[i + 1])
            out.append(nxt * 2)
            i += 2
            continue
        out.append(_tok_to_chars(tok))
        i += 1
    code = "".join(out).upper()
    code = re.sub(r"-+", "-", code).strip("-")
    if re.fullmatch(r"AM[A-Z0-9]{4,}", code):
        code = "AM-" + code[2:]
    return code if re.fullmatch(r"[A-Z0-9][A-Z0-9-]{3,19}", code) else None


def _tok_to_chars(tok: str) -> str:
    if tok in ("dash", "hyphen", "minus", "-"):
        return "-"
    if tok in _DIGITS:
        return _DIGITS[tok]
    if tok in _NATO:
        return _NATO[tok]
    if tok in _LETTER_SOUNDS:
        return _LETTER_SOUNDS[tok]
    return tok


_CONFUSABLE = {"O": "0", "0": "O", "I": "1", "1": "I", "S": "5", "5": "S", "B": "8", "8": "B", "Z": "2", "2": "Z"}


def code_candidates(code: str, limit: int = 32) -> List[str]:
    """The code as heard first, then variants swapping look/sound-alike characters (O<->0, I<->1 ...)."""
    prefix, sep, tail = code.partition("-")
    body = tail if sep else code
    opts = [(c, _CONFUSABLE[c]) if c in _CONFUSABLE else (c,) for c in body]
    out = []
    for combo in product(*opts):
        cand = "".join(combo)
        out.append(f"{prefix}-{cand}" if sep else cand)
        if len(out) >= limit:
            break
    out.sort(key=lambda c: c != code)  # heard version first
    return out


def spell_code(code: str) -> str:
    """Read a meeting code clearly: 'A, M, dash, X, D, J, zero, J, E'."""
    words = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
             "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine", "-": "dash"}
    return ", ".join(words.get(c, c) for c in code.upper())


def extract_meeting_title(text: str) -> Optional[str]:
    """'create a meeting called weekly sync' -> 'Weekly Sync'. Returns None if no title was spoken."""
    t = (text or "").strip()
    m = re.search(r"\b(?:called|named|titled|title|about|for)\s+(?:the\s+|a\s+)?(.+)$", t, flags=re.I)
    if m:
        cand = m.group(1)
    else:
        cand = re.sub(r"^\s*(?:please\s+)?(?:create|start|make|new|host|set up|setup)\s+(?:a\s+|an\s+|the\s+)?"
                      r"(?:new\s+)?(?:meeting|room|call)?\s*", "", t, flags=re.I)
    cand = re.sub(r"[^\w\s'&-]", "", cand).strip()
    cand = re.sub(r"^(?:meeting|called|named)\s+", "", cand, flags=re.I).strip()
    return cand.title() if len(cand) >= 3 else None
