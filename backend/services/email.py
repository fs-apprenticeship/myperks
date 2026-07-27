from __future__ import annotations

import logging

import httpx

from settings import settings

logger = logging.getLogger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


async def _resend_send(to: str, subject: str, body: str) -> None:
    api_key = settings.resend_api_key.get_secret_value()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            _RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": settings.notifications_from_email,
                "to": [to],
                "subject": subject,
                "text": body,
            },
            timeout=10,
        )
        response.raise_for_status()


async def send_email(to: str, subject: str, body: str) -> None:
    """
    Send a plain-text email to ``to``.

    Flag-guarded and non-raising: a no-op when email notifications are disabled,
    and any provider error is caught and logged rather than propagated.
    """
    if not settings.notifications_email_enabled:
        logger.info("Email notifications disabled: skipping send to %s", to)
        return
    try:
        await _resend_send(to, subject, body)
    except Exception:
        logger.exception("Failed to send email to %s (subject=%r)", to, subject)
    else:
        logger.info("Sent email to %s (subject=%r)", to, subject)
