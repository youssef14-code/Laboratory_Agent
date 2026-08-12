from datetime import datetime, timedelta, timezone

from models.models import Subscription, db


class SubscriptionService:

    # ==========================================================
    # Getters
    # ==========================================================

    @staticmethod
    def get_subscription_by_laboratory_id(laboratory_id):
        return Subscription.query.filter_by(
            laboratory_id=laboratory_id
        ).first()

    @staticmethod
    def get_by_page(page):
        return SubscriptionService.get_subscription_by_laboratory_id(
            page.laboratory_id
        )

    @staticmethod
    def messages_remaining(subscription):
        if not subscription:
            return 0

        return max(
            subscription.message_limit - subscription.message_used,
            0,
        )

    @staticmethod
    def grace_remaining(subscription):
        if not subscription:
            return 0

        extra = max(
            subscription.message_used - subscription.message_limit,
            0,
        )

        return max(
            subscription.grace_limit - extra,
            0,
        )

    @staticmethod
    def usage_percentage(subscription):
        if not subscription:
            return 0

        if subscription.message_limit == 0:
            return 0

        return round(
            (subscription.message_used / subscription.message_limit) * 100,
            1,
        )

    # ==========================================================
    # AI Permission
    # ==========================================================

    @staticmethod
    def can_use_ai(subscription):

        if not subscription:
            return False, "No subscription."

        if not subscription.is_active:
            return False, "Subscription suspended."

        if subscription.message_used >= (
            subscription.message_limit +
            subscription.grace_limit
        ):
            return False, "Message limit exceeded."

        return True, "OK"

    @staticmethod
    def consume(subscription, count=1, cost=None):

        if not subscription:
            return

        subscription.message_used += count
        if cost is not None:
            subscription.estimated_cost = round(subscription.estimated_cost + cost, 6)

        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()

    @staticmethod
    def add_estimated_cost(subscription, amount):

        if not subscription:
            return

        subscription.estimated_cost = round(subscription.estimated_cost + amount, 6)
        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()

    # ==========================================================
    # Status
    # ==========================================================

    @staticmethod
    def get_status(subscription):

        if not subscription:
            return {
                "text": "No Subscription",
                "color": "danger",
            }

        if not subscription.is_active:
            return {
                "text": "Suspended",
                "color": "danger",
            }

        if subscription.message_used >= (
            subscription.message_limit +
            subscription.grace_limit
        ):
            return {
                "text": "Limit Reached",
                "color": "warning",
            }

        return {
            "text": "Active",
            "color": "success",
        }

    # ==========================================================
    # Alerts
    # ==========================================================

    @staticmethod
    def get_alert(subscription):

        if not subscription:
            return {
                "type": "danger",
                "message": "No subscription found.",
            }

        if not subscription.is_active:
            return {
                "type": "danger",
                "message": "AI service is suspended.",
            }

        remaining = SubscriptionService.messages_remaining(
            subscription
        )

        if remaining == 0:

            grace = SubscriptionService.grace_remaining(
                subscription
            )

            if grace > 0:

                return {
                    "type": "warning",
                    "message": f"Main limit reached. {grace} grace messages remaining.",
                }

            return {
                "type": "danger",
                "message": "Message limit exceeded.",
            }

        if remaining <= 500:

            return {
                "type": "warning",
                "message": f"Only {remaining} messages remaining.",
            }

        return None

    # ==========================================================
    # Renew
    # ==========================================================

    @staticmethod
    def renew(subscription, months=1):

        if not subscription:
            return

        now = datetime.now(timezone.utc)

        subscription.message_used = 0
        subscription.is_active = True

        subscription.start_date = now
        subscription.end_date = now + timedelta(days=30 * months)

        subscription.renew_count += 1
        subscription.last_renewed_at = now
        subscription.updated_at = now

        db.session.commit()

    # ==========================================================
    # Reset Usage
    # ==========================================================

    @staticmethod
    def reset_usage(subscription):

        if not subscription:
            return

        subscription.message_used = 0
        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()

    # ==========================================================
    # Suspend / Activate
    # ==========================================================

    @staticmethod
    def suspend(subscription):

        if not subscription:
            return

        subscription.is_active = False
        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()

    @staticmethod
    def activate(subscription):

        if not subscription:
            return

        subscription.is_active = True
        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()


  


    @staticmethod
    def update_limit(subscription, message_limit):
        if not subscription:
            return 

        subscription.message_limit = int(message_limit)
        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()    

    @staticmethod
    def update_grace_limit(subscription, grace_limit):
        if not subscription:
            return

        subscription.grace_limit = int(grace_limit)
        subscription.updated_at = datetime.now(timezone.utc)

        db.session.commit()