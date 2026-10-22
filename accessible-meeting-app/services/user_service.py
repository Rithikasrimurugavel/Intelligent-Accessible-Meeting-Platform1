import uuid
from typing import Any, Dict, Optional, Tuple

from services.supabase_service import supabase_service
from utils.logger import logger
from utils.validation import validate_email, validate_user_input


class UserService:
    @staticmethod
    def register_user(name: str, email: str, role: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Create a profile, or update name/role if the email already exists."""
        valid, msg = validate_user_input(name, email, role)
        if not valid:
            return False, None, msg
        email = email.strip().lower()
        try:
            existing = supabase_service.get_user_by_email(email)
            user_id = existing["id"] if existing else str(uuid.uuid4())
            profile = supabase_service.create_user_profile(user_id, email, name.strip(), role.lower())
            return True, profile, "User profile saved."
        except Exception as e:
            logger.error(f"register_user error: {e}")
            return False, None, f"Registration failed: {e}"

    @staticmethod
    def login_user(name: str, email: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Return the existing profile for this email, or create a new 'normal' one."""
        if not validate_email(email):
            return False, None, "Please enter a valid email address."
        try:
            existing = supabase_service.get_user_by_email(email)
            if existing:
                return True, existing, "Welcome back."
        except Exception as e:
            logger.error(f"login_user error: {e}")
            return False, None, f"Login failed: {e}"
        return UserService.register_user(name, email, "normal")

    @staticmethod
    def update_role(user: Dict[str, Any], role: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        try:
            profile = supabase_service.create_user_profile(user["id"], user["email"], user["name"], role)
            return True, profile, "Role updated."
        except Exception as e:
            logger.error(f"update_role error: {e}")
            return False, None, f"Could not save role: {e}"


user_service = UserService()
