"""Plain-text email over SMTP (optional). Without CLIPSTAR_SMTP_HOST nothing is sent."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .config import get_settings
from .errors import PermanentError, RetryableError


def configured() -> bool:
    st = get_settings()
    return bool(st.smtp_host and (st.smtp_from or st.smtp_user))


def send(to: list[str], subject: str, body: str) -> None:
    st = get_settings()
    if not configured() or not to:
        return
    msg = EmailMessage()
    msg["From"] = st.smtp_from or st.smtp_user
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if st.smtp_port == 465:
            server = smtplib.SMTP_SSL(st.smtp_host, st.smtp_port, timeout=30, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(st.smtp_host, st.smtp_port, timeout=30)
        with server:
            if st.smtp_port != 465 and st.smtp_starttls:
                server.starttls(context=ssl.create_default_context())
            if st.smtp_user:
                server.login(st.smtp_user, st.smtp_password or "")
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise PermanentError(str(e), user_message="The email server rejected the login. Check CLIPSTAR_SMTP_USER and CLIPSTAR_SMTP_PASSWORD.") from e
    except smtplib.SMTPRecipientsRefused as e:
        raise PermanentError(str(e), user_message="The email server refused the recipient address.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise RetryableError(str(e), user_message="Couldn't reach the email server; will retry.") from e
