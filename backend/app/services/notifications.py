import logging

from app.interfaces.interfaces import ISyncNotifier
from app.observability import log_event

logger = logging.getLogger(__name__)


def mask_email(email: str) -> str:
    local_part, separator, domain = email.partition("@")
    if not separator:
        return "***"
    visible_prefix = local_part[:1]
    return f"{visible_prefix}***@{domain}"


class MockStudentNotifier(ISyncNotifier):
    """Notificações de cadastro/revisão em modo demo; o conteúdo não é registado."""

    def send_notification(self, recipient: str, message: str) -> None:
        log_event(
            logger,
            "student.notification.sent",
            provider="mock",
            recipient=mask_email(recipient),
            message_length=len(message),
        )
