from typing import Any, Dict, List, Optional, Tuple

from services.huggingface_service import huggingface_service
from services.supabase_service import supabase_service
from utils.logger import logger


class MessageService:
    @staticmethod
    def send_text_message(meeting_id, sender_id, sender_name, sender_role, text
                          ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        clean = (text or "").strip()
        if not clean:
            return False, None, "Message cannot be empty."
        try:
            msg = supabase_service.send_message(meeting_id, sender_id, sender_name, sender_role,
                                                "text", clean, clean, 1.0)
            return True, msg, "Message sent."
        except Exception as e:
            logger.error(f"send_text_message error: {e}")
            return False, None, f"Failed to send message: {e}"

    @staticmethod
    def process_and_send_voice_message(meeting_id, sender_id, sender_name, sender_role, audio_bytes: bytes
                                       ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        if not audio_bytes or len(audio_bytes) < 100:
            return False, None, "Invalid or empty audio recorded."
        stt = huggingface_service.speech_to_text(audio_bytes)
        if not stt.get("success") or not stt.get("text"):
            return False, None, f"Speech recognition failed: {stt.get('error', 'Unable to transcribe audio.')}"
        text = stt["text"]
        try:
            msg = supabase_service.send_message(meeting_id, sender_id, sender_name, sender_role, "voice",
                                                text, "[Voice Recording Captured]", stt.get("confidence"))
            note = f" ({stt['note']})" if stt.get("simulated") else ""
            return True, msg, f"Voice transcribed: '{text}'{note}"
        except Exception as e:
            logger.error(f"voice message error: {e}")
            return False, None, f"Failed to save voice message: {e}"

    @staticmethod
    def send_voice_text_message(meeting_id, sender_id, sender_name, sender_role, text: str,
                                confidence: Optional[float] = None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Post text that the browser's speech recognizer already transcribed (voice assistant 'talk mode')."""
        clean = (text or "").strip()
        if not clean:
            return False, None, "Nothing to send."
        try:
            msg = supabase_service.send_message(meeting_id, sender_id, sender_name, sender_role, "voice",
                                                clean, "[Voice Recording Captured]", confidence)
            return True, msg, "Message sent."
        except Exception as e:
            logger.error(f"voice text message error: {e}")
            return False, None, f"Failed to send message: {e}"

    @staticmethod
    def process_and_send_sign_message(meeting_id, sender_id, sender_name, sender_role, detected_sign: str,
                                      confidence: float = 0.90) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        clean = (detected_sign or "").strip()
        if not clean:
            return False, None, "No sign recognized."
        try:
            msg = supabase_service.send_message(meeting_id, sender_id, sender_name, sender_role, "sign_language",
                                                clean, f"[Sign Gesture Detected: {clean}]", confidence)
            return True, msg, f"Sign message sent: '{clean}'"
        except Exception as e:
            logger.error(f"sign message error: {e}")
            return False, None, f"Failed to send sign message: {e}"

    @staticmethod
    def send_system_message(meeting_id: str, text: str) -> Optional[Dict[str, Any]]:
        try:
            return supabase_service.send_message(meeting_id, None, "System", "system", "system", text, None, 1.0)
        except Exception as e:
            logger.error(f"system message error: {e}")
            return None

    @staticmethod
    def get_meeting_messages(meeting_id: str) -> List[Dict[str, Any]]:
        try:
            return supabase_service.get_messages(meeting_id)
        except Exception as e:
            logger.error(f"get_messages error: {e}")
            return []


message_service = MessageService()
