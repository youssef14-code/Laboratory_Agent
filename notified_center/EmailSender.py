import os
import smtplib
import logging
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from software_service.tenant_services import TenantService
import json
import base64
from email.header import Header
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
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

def send_visit_confirmation_email(
    reference_id: str,
    name: str,
    phone: str,
    address: str,
    details: str,
    date: str,
    comes_from: str,
) -> bool:
    """
    Sends a home visit booking confirmation email using Gmail API with automatic token refresh handling.
    """
    try:
        # Fetch default tenant settings
        settings = TenantService.get_tenant_settings("default_tenant")

        if not settings or not settings.notification_email or not settings.gmail_token_json:
            logger.error("[NotificationCenter] Missing settings, email, or token for home visit notification.")
            return False

        # Build email body
        email_body = (
            f"New Home Visit Booking\n\n"
            f"Reference ID: {reference_id}\n"
            f"Patient Name: {name}\n"
            f"Phone: {phone}\n"
            f"Address: {address}\n"
            f"Lab Tests: {details}\n"
            f"Date: {date}\n"
            f"Source: {comes_from}\n"
        )
        subject = f"New Home Visit Booking - #{reference_id}"
        recipients = [r.strip() for r in settings.notification_email.split(",") if r.strip()]

        # Setup credentials
        SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
        token_info = json.loads(settings.gmail_token_json)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

        # Refresh token handling
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                settings.gmail_token_json = creds.to_json()
                # db.session.commit()  # فك الكومنت لو عايز تحفظ التوكن الجديد في الـ DB
            except RefreshError as refresh_err:
                logger.error("[NotificationCenter] Refresh token expired/revoked: %s", refresh_err)
                send_production_alert(
                    subject="Gmail OAuth Refresh Token Failure",
                    body_or_error=refresh_err,
                    context={"reference_id": reference_id, "recipients": recipients},
                )
                return False

        gmail_service = build("gmail", "v1", credentials=creds)

        # Send email to each recipient
        for recipient in recipients:
            msg = MIMEText(email_body, "plain", "utf-8")
            msg["To"] = recipient
            msg["Subject"] = Header(subject, "utf-8")
            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
            gmail_service.users().messages().send(
                userId="me",
                body={"raw": raw_message},
            ).execute()

        logger.info("[NotificationCenter] Booking email sent successfully to %s", recipients)
        return True

    except Exception as e:
        logger.exception("[NotificationCenter] Failed to send home visit notification: %s", e)
        send_production_alert(
            subject=f"Home Visit Notification Delivery Failure (#{reference_id})",
            body_or_error=e,
            context={"reference_id": reference_id, "patient_name": name, "phone": phone},
        )
        return False


def send_pending_prescription_email(
    inquiry_id: int,
    comes_from: str,
    confidence_score: float,
    extracted_tests: str,
    ocr_extracted_text: str = "",
) -> bool:
    """
    Sends an email alert when a prescription is saved with PENDING status
    (low OCR confidence requiring manual doctor review).
    Uses the same Gmail API flow as send_visit_confirmation_email.
    """
    try:
        # Fetch default tenant settings
        settings = TenantService.get_tenant_settings("default_tenant")

        if not settings or not settings.notification_email or not settings.gmail_token_json:
            logger.error("[NotificationCenter] Missing settings, email, or token for pending prescription notification.")
            return False

        # Build email body
        email_body = (
            f"⚠️ New Pending Prescription – Doctor Review Required\n\n"
            f"Inquiry ID: {inquiry_id}\n"
            f"Source: {comes_from}\n"
            f"OCR Confidence: {confidence_score:.2f}\n"
            f"This prescription has low OCR confidence and requires manual review.\n"
            f"Please log in to the dashboard to review and confirm the required tests.\n"
        )
        subject = f"⚠️ Pending Prescription Review – Inquiry #{inquiry_id}"
        # Parse comma-separated recipients
        recipients = [r.strip() for r in settings.notification_email.split(",") if r.strip()]

        # Setup credentials
        SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
        token_info = json.loads(settings.gmail_token_json)
        creds = Credentials.from_authorized_user_info(token_info, SCOPES)

        # 🛠️ Refresh token handling
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                if hasattr(settings, 'gmail_token_json'):
                    settings.gmail_token_json = creds.to_json()
            except RefreshError as refresh_err:
                logger.error("[NotificationCenter] Refresh token expired/revoked: %s", refresh_err)
                send_production_alert(
                    subject="Gmail OAuth Refresh Token Failure (Pending Prescription)",
                    body_or_error=refresh_err,
                    context={"inquiry_id": inquiry_id, "recipients": recipients},
                    level="ERROR"
                )
                return False

        gmail_service = build("gmail", "v1", credentials=creds)

        # Send email to each recipient
        for recipient in recipients:
            message = (
                f"To: {recipient}\r\n"
                f"Subject: {subject}\r\n"
                f"\r\n"
                f"{email_body}"
            )
            raw_message = base64.urlsafe_b64encode(message.encode("utf-8")).decode("utf-8")
            gmail_service.users().messages().send(
                userId="me",
                body={"raw": raw_message},
            ).execute()

        logger.info("[NotificationCenter] Pending prescription email sent successfully to %s | inquiry_id=%s", recipients, inquiry_id)
        return True

    except Exception as e:
        logger.exception("[NotificationCenter] Failed to send pending prescription notification: %s", e)
        send_production_alert(
            subject=f"Pending Prescription Notification Delivery Failure (Inquiry #{inquiry_id})",
            body_or_error=e,
            context={"inquiry_id": inquiry_id, "comes_from": comes_from},
            level="ERROR"
        )
        return False


def send_new_complaint_email(phone: str, complaint_text: str, comes_from: str) -> bool:
    """Sends an email alert when a new customer complaint is registered."""
    try:
        settings = TenantService.get_tenant_settings("default_tenant")
        if not settings or not settings.notification_email or not settings.gmail_token_json:
            logger.error("[NotificationCenter] Missing settings/email/token for complaint notification.")
            return False

        subject = f"New Customer Complaint - {phone}"
        email_body = (
            f"New Customer Complaint\n\n"
            f"Phone: {phone}\n"
            f"Source: {comes_from}\n\n"
            f"Complaint:\n{complaint_text}\n"
        )
        recipients = [r.strip() for r in settings.notification_email.split(",") if r.strip()]

        creds = Credentials.from_authorized_user_info(
            json.loads(settings.gmail_token_json),
            ["https://www.googleapis.com/auth/gmail.send"],
        )
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                settings.gmail_token_json = creds.to_json()
            except RefreshError as refresh_err:
                logger.error("[NotificationCenter] Refresh token expired/revoked: %s", refresh_err)
                send_production_alert("Gmail OAuth Refresh Token Failure (Complaint)", refresh_err)
                return False

        gmail_service = build("gmail", "v1", credentials=creds)

        for recipient in recipients:
            msg = MIMEText(email_body, "plain", "utf-8")  # utf-8 so Arabic text isn't garbled
            msg["To"] = recipient
            msg["Subject"] = Header(subject, "utf-8")
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            gmail_service.users().messages().send(userId="me", body={"raw": raw}).execute()

        logger.info("[NotificationCenter] Complaint email sent to %s", recipients)
        return True

    except Exception as e:
        logger.exception("[NotificationCenter] Failed to send complaint notification: %s", e)
        send_production_alert("Complaint Notification Delivery Failure", e, context={"phone": phone})
        return False