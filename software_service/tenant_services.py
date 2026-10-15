import logging
from typing import Optional
from models.models import db, TenantSettings

logger = logging.getLogger(__name__)


class TenantService:
    """Service layer encapsulating all operations on TenantSettings."""

    @staticmethod
    def get_tenant_settings(tenant_id: str = "default_tenant") -> Optional[TenantSettings]:
        """Fetch TenantSettings for a tenant_id, or None if missing or on error."""
        try:
            return TenantSettings.query.filter_by(tenant_id=tenant_id).first()
        except Exception:
            logger.exception("[TenantService.get_tenant_settings] failed")
            return None

    @staticmethod
    def get_or_create_tenant_settings(tenant_id: str = "default_tenant") -> TenantSettings:
        """
        Fetch existing TenantSettings or add a new row to the session.

        Does not commit; the save_* methods commit.
        """
        tenant = TenantSettings.query.filter_by(tenant_id=tenant_id).first()
        if not tenant:
            tenant = TenantSettings(tenant_id=tenant_id)
            db.session.add(tenant)
        return tenant

    @staticmethod
    def save_gmail_credentials(credentials_json: str, tenant_id: str = "default_tenant") -> TenantSettings:
        """Save the serialized Gmail OAuth token JSON. Rolls back and re-raises on failure."""
        try:
            tenant = TenantService.get_or_create_tenant_settings(tenant_id)
            tenant.gmail_token_json = credentials_json
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[TenantService.save_gmail_credentials] failed for tenant_id=%s", tenant_id)
            raise
        logger.info("[TenantService] Saved Gmail credentials for tenant_id=%s", tenant_id)
        return tenant

    @staticmethod
    def save_notification_email(recipient_email: str, tenant_id: str = "default_tenant") -> TenantSettings:
        """Save the notification email address. Rolls back and re-raises on failure."""
        try:
            tenant = TenantService.get_or_create_tenant_settings(tenant_id)
            tenant.notification_email = recipient_email
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception("[TenantService.save_notification_email] failed for tenant_id=%s", tenant_id)
            raise
        logger.info("[TenantService] Saved notification email for tenant_id=%s", tenant_id)
        return tenant