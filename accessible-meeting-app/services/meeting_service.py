from typing import Any, Dict, List, Optional, Tuple

from services.supabase_service import supabase_service
from utils.helpers import generate_meeting_code
from utils.logger import logger
from utils.validation import validate_meeting_code


class MeetingService:
    @staticmethod
    def create_meeting(title: str, host_id: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        if not title or len(title.strip()) < 3:
            return False, None, "Meeting title must be at least 3 characters long."
        try:
            meeting = supabase_service.create_meeting(generate_meeting_code(), title.strip(), host_id)
            logger.info(f"Meeting created: {meeting['meeting_code']}")
            return True, meeting, "Meeting created successfully."
        except Exception as e:
            logger.error(f"create_meeting error: {e}")
            return False, None, f"Failed to create meeting: {e}"

    @staticmethod
    def join_meeting(meeting_code: str, user_id: str, role: str
                     ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
        """Join using the meeting CODE (e.g. AM-8F3K92)."""
        if not validate_meeting_code(meeting_code):
            return False, None, None, "Invalid meeting code format."
        try:
            meeting = supabase_service.get_meeting_by_code(meeting_code)
            if not meeting:
                return False, None, None, f"No meeting found with code '{meeting_code.strip().upper()}'."
            if meeting.get("status") == "ended":
                return False, None, None, "This meeting has already ended."
            participant = supabase_service.join_meeting(meeting["id"], user_id, role)
            return True, meeting, participant, f"Successfully joined meeting: {meeting['title']}"
        except Exception as e:
            logger.error(f"join_meeting error: {e}")
            return False, None, None, f"Failed to join meeting: {e}"

    @staticmethod
    def refresh_meeting(meeting_code: str) -> Optional[Dict[str, Any]]:
        try:
            return supabase_service.get_meeting_by_code(meeting_code)
        except Exception as e:
            logger.error(f"refresh_meeting error: {e}")
            return None

    @staticmethod
    def get_participants(meeting_id: str) -> List[Dict[str, Any]]:
        try:
            return supabase_service.get_participants(meeting_id)
        except Exception as e:
            logger.error(f"get_participants error: {e}")
            return []

    @staticmethod
    def leave_meeting(meeting_id: str, user_id: str) -> bool:
        try:
            return supabase_service.leave_meeting(meeting_id, user_id)
        except Exception as e:
            logger.error(f"leave_meeting error: {e}")
            return False

    @staticmethod
    def end_meeting(meeting_id: str) -> bool:
        try:
            return supabase_service.end_meeting(meeting_id)
        except Exception as e:
            logger.error(f"end_meeting error: {e}")
            return False


meeting_service = MeetingService()
