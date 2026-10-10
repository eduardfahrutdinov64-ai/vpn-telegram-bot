"""Бизнес-логика подписок. Не зависит от Telegram — её легко тестировать и переиспользовать."""
from dataclasses import dataclass
from datetime import timedelta

from app.config import config, get_location
from app.db import Database, User, utcnow
from app.tariffs import Tariff, get_tariff
from app.vpn import KeyProvider


@dataclass
class PaymentResult:
    user: User
    referrer: User | None  # кому начислен реферальный бонус (если начислен)


class SubscriptionService:
    def __init__(self, db: Database, provider: KeyProvider):
        self.db = db
        self.provider = provider

    # ---------- регистрация ----------
    def register(self, user_id: int, username: str | None, first_name: str | None,
                 start_arg: str | None = None) -> tuple[User, bool]:
        referrer_id = None
        if start_arg and start_arg.startswith("ref_") and start_arg[4:].isdigit():
            referrer_id = int(start_arg[4:])
        return self.db.upsert_user(user_id, username, first_name, referrer_id)

    # ---------- продление ----------
    async def extend(self, user_id: int, days: int) -> User:
        user = self.db.get_user(user_id)
        now = utcnow()
        base = user.sub_until if user.sub_until and user.sub_until > now else now
        until = base + timedelta(days=days)
        location = get_location(user.location)
        key = await self.provider.issue_key(user_id, location, until)
        self.db.update_user(user_id, sub_until=until, vpn_key=key, location=location.code, reminded_for=None)
        return self.db.get_user(user_id)

    async def start_trial(self, user_id: int) -> User | None:
        """Включает пробный период. None — если пробный период уже использован или есть подписка."""
        user = self.db.get_user(user_id)
        if user.trial_used or user.is_active:
            return None
        self.db.update_user(user_id, trial_used=True)
        return await self.extend(user_id, config.trial_days)

    async def apply_payment(self, user_id: int, tariff: Tariff, charge_id: str | None, demo: bool) -> PaymentResult:
        first_payment = self.db.count_paid(user_id) == 0
        self.db.add_payment(user_id, tariff.id, tariff.stars, charge_id, demo)
        user = await self.extend(user_id, tariff.days)

        referrer = None
        if first_payment and user.referrer_id and config.referral_bonus_days > 0:
            if self.db.get_user(user.referrer_id):
                referrer = await self.extend(user.referrer_id, config.referral_bonus_days)
        return PaymentResult(user=user, referrer=referrer)

    async def change_location(self, user_id: int, code: str) -> User:
        user = self.db.get_user(user_id)
        new_location = get_location(code)
        if user.is_active:
            await self.provider.revoke_key(user_id, get_location(user.location))
            key = await self.provider.issue_key(user_id, new_location, user.sub_until)
            self.db.update_user(user_id, location=new_location.code, vpn_key=key)
        else:
            self.db.update_user(user_id, location=new_location.code)
        return self.db.get_user(user_id)

    async def refund(self, charge_id: str) -> User | None:
        """Отмечает платёж возвращённым и списывает оплаченные дни. Звёзды возвращает хендлер."""
        payment = self.db.get_payment_by_charge(charge_id)
        if payment is None or payment["refunded"]:
            return None
        self.db.mark_refunded(charge_id)
        user = self.db.get_user(payment["user_id"])
        tariff = get_tariff(payment["tariff_id"])
        if user.sub_until and tariff:
            until = user.sub_until - timedelta(days=tariff.days)
            self.db.update_user(user.id, sub_until=until)
            if until <= utcnow():
                await self.provider.revoke_key(user.id, get_location(user.location))
        return self.db.get_user(user.id)

    def due_reminders(self) -> list[User]:
        """Пользователи, у которых подписка закончится в ближайшие 24 часа и кого ещё не предупредили."""
        now = utcnow()
        users = self.db.users_expiring_between(now, now + timedelta(hours=24))
        return [u for u in users if u.reminded_for != u.sub_until.isoformat()]

    def mark_reminded(self, user: User) -> None:
        self.db.update_user(user.id, reminded_for=user.sub_until.isoformat())
