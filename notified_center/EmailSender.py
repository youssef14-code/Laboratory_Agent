import os
import smtplib
import logging
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
load_dotenv() 

logger = logging.getLogger(__name__)

SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
IMAP_SERVER = os.environ.get("IMAP_SERVER", "")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))


class EmailClient:
    def __init__(self, smtp_server=None, smtp_port=None, imap_server=None, imap_port=None):
        self.smtp_server = smtp_server or os.environ.get("SMTP_SERVER", "")
        self.smtp_port = int(smtp_port or os.environ.get("SMTP_PORT", "465"))
        self.imap_server = imap_server or os.environ.get("IMAP_SERVER", "")
        self.imap_port = int(imap_port or os.environ.get("IMAP_PORT", "993"))

    # =========================
    # SMTP Send
    # =========================
    def send_email(self, subject, body):
        sender = os.environ.get("NOTIFICATION_EMAIL_SENDER", "")
        password = os.environ.get("NOTIFICATION_EMAIL_PASSWORD", "")
        receivers_str = os.environ.get("NOTIFICATION_EMAIL_RECEIVERS", "")
        receivers = [r.strip() for r in receivers_str.split(",") if r.strip()]

        if not sender or not password or not receivers:
            logger.error("[NotificationCenter] Missing email credentials or receivers in environment.")
            return False

        machine_identifier = os.environ.get("SERVER_IDENTIFIER", "ikhtiar-labs-app")
        final_body = f"{machine_identifier}\n\n{body}"

        try:
            with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=15) as server:
                server.login(sender, password)
                for receiver in receivers:
                    msg = MIMEMultipart()
                    msg["From"] = sender
                    msg["To"] = receiver
                    msg["Subject"] = subject
                    msg.attach(MIMEText(final_body, "plain"))
                    server.send_message(msg)
            logger.info("[NotificationCenter] Email sent: '%s' to %s", subject, receivers)
            return True
        except Exception as e:
            logger.error("[NotificationCenter] SMTP Error sending email '%s': %s", subject, e, exc_info=True)
            return False


email_client = EmailClient()


def send_production_alert(subject: str, body_or_error, context: dict = None):
    """
    Centralized helper function to send production alert notifications.
    Included in context: page_id, client_id, booking_id, sender_id, etc.
    """
    if isinstance(body_or_error, Exception):
        error_str = f"Exception Type: {type(body_or_error).__name__}\nDetails: {str(body_or_error)}\nTraceback:\n{traceback.format_exc()}"
    else:
        error_str = str(body_or_error)

    context_str = ""
    if context and isinstance(context, dict):
        context_lines = [f"  - {k}: {v}" for k, v in context.items() if v is not None]
        if context_lines:
            context_str = "\nContext Information:\n" + "\n".join(context_lines)

    body = f"PRODUCTION FAILURE DETECTED\nSubject: {subject}\n\n{error_str}\n{context_str}"
    return email_client.send_email(subject=f"[Alert] {subject}", body=body)


    