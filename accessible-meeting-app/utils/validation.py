import re
from typing import Tuple

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{3,19}$")
VALID_ROLES = {"manager", "normal", "blind", "deaf", "mute"}


def validate_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


def validate_meeting_code(code: str) -> bool:
    return bool(code) and bool(_CODE_RE.match(code.strip().upper()))


def validate_user_input(name: str, email: str, role: str) -> Tuple[bool, str]:
    if not name or len(name.strip()) < 2:
        return False, "Name must be at least 2 characters long."
    if not validate_email(email):
        return False, "Please provide a valid email address."
    if not role or role.lower() not in VALID_ROLES:
        return False, f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}"
    return True, "Validation successful."
