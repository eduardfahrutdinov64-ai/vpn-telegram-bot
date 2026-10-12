"""
NovaVPN — Telegram-бот для продажи VPN-подписок. Весь код в одном файле.

Возможности: пробный период, тарифы с оплатой в Telegram Stars (+ демо-оплата),
ключ VLESS с QR-кодом, смена локации, инструкции для устройств, рефералы,
напоминания об окончании подписки, админ-команды.

Запуск:
    pip install "aiogram>=3.13,<4" "qrcode[pil]" python-dotenv tzdata
    python vpn_bot.py

Настройки — в блоке НАСТРОЙКИ ниже или в файле .env рядом со скриптом
(значения из .env важнее). Обязательно укажите BOT_TOKEN и ADMIN_IDS.
"""
import asyncio
import logging
import os
import sqlite3
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from io import BytesIO
from urllib.parse import quote
from zoneinfo import ZoneInfo

import qrcode
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (BotCommand, BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, LabeledPrice, Message, PreCheckoutQuery)
from aiogram.utils.keyboard import InlineKeyboardBuilder

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv не обязателен, если всё задано в блоке НАСТРОЙКИ
    pass

# =====================================================================
# НАСТРОЙКИ
# =====================================================================

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or ""                     # токен от @BotFather
ADMIN_IDS = {int(x) for x in (os.getenv("ADMIN_IDS") or os.getenv("ID") or "").replace(" ", "").split(",") if x}  # ваш ID: @userinfobot
SERVICE_NAME = os.getenv("SERVICE_NAME", "NovaVPN")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "novavpn_support").lstrip("@")
DEMO_PAYMENTS = os.getenv("DEMO_PAYMENTS", "true").strip().lower() in ("1", "true", "yes", "on", "да")
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "3"))             # 0 — без пробного периода
REFERRAL_BONUS_DAYS = int(os.getenv("REFERRAL_BONUS_DAYS", "7"))
try:
    TZ = ZoneInfo(os.getenv("TZ_NAME", "Europe/Moscow"))
except Exception:  # на Windows нет базы часовых поясов без пакета tzdata — берём МСК (UTC+3)
    TZ = timezone(timedelta(hours=3), "MSK")
DB_PATH = os.getenv("DB_PATH", "vpn_bot.sqlite3")
REMINDER_CHECK_SECONDS = 30 * 60


@dataclass(frozen=True)
class Tariff:
    id: str
    title: str
    days: int
    stars: int
    badge: str = ""

    @property
    def button_text(self) -> str:
        return f"{self.title} — {self.stars} ⭐" + (f" · {self.badge}" if self.badge else "")


# Тарифы: код, название, дней, цена в звёздах, метка
TARIFFS = [
    Tariff("m1", "1 месяц", 30, 100),
    Tariff("m3", "3 месяца", 90, 270, "−10%"),
    Tariff("m6", "6 месяцев", 180, 500, "−17%"),
    Tariff("m12", "12 месяцев", 365, 900, "−25%"),
]


@dataclass(frozen=True)
class Location:
    code: str
    title: str
    host: str


# Локации серверов. Для реального сервиса замените host на адреса своих серверов.
LOCATIONS = [
    Location("nl", "🇳🇱 Нидерланды", "nl.example-vpn.com"),
    Location("de", "🇩🇪 Германия", "de.example-vpn.com"),
    Location("fi", "🇫🇮 Финляндия", "fi.example-vpn.com"),
]


def get_tariff(tariff_id: str) -> Tariff | None:
    return next((t for t in TARIFFS if t.id == tariff_id), None)


def get_location(code: str | None) -> Location:
    return next((loc for loc in LOCATIONS if loc.code == code), LOCATIONS[0])


log = logging.getLogger("vpn_bot")


# =====================================================================
# БАЗА ДАННЫХ (SQLite)
# =====================================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass
class User:
    id: int
    username: str | None
    first_name: str | None
    created_at: datetime
    referrer_id: int | None
    trial_used: bool
    sub_until: datetime | None
    location: str | None
    vpn_key: str | None
    reminded_for: str | None
    blocked: bool

    @property
    def is_active(self) -> bool:
        return self.sub_until is not None and self.sub_until > utcnow()


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, created_at TEXT NOT NULL,
    referrer_id INTEGER, trial_used INTEGER NOT NULL DEFAULT 0, sub_until TEXT,
    location TEXT, vpn_key TEXT, reminded_for TEXT, blocked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, tariff_id TEXT NOT NULL,
    stars INTEGER NOT NULL, charge_id TEXT, demo INTEGER NOT NULL DEFAULT 0,
    refunded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _user(row) -> User | None:
        if row is None:
            return None
        return User(id=row["id"], username=row["username"], first_name=row["first_name"],
                    created_at=_to_dt(row["created_at"]), referrer_id=row["referrer_id"],
                    trial_used=bool(row["trial_used"]), sub_until=_to_dt(row["sub_until"]),
                    location=row["location"], vpn_key=row["vpn_key"],
                    reminded_for=row["reminded_for"], blocked=bool(row["blocked"]))

    def get_user(self, user_id: int) -> User | None:
        with self._conn() as c:
            return self._user(c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def upsert_user(self, user_id: int, username: str | None, first_name: str | None,
                    referrer_id: int | None = None) -> tuple[User, bool]:
        existing = self.get_user(user_id)
        with self._conn() as c:
            if existing:
                c.execute("UPDATE users SET username=?, first_name=?, blocked=0 WHERE id=?",
                          (username, first_name, user_id))
                created = False
            else:
                if referrer_id == user_id or (referrer_id and not self.get_user(referrer_id)):
                    referrer_id = None
                c.execute("INSERT INTO users (id, username, first_name, created_at, referrer_id) VALUES (?,?,?,?,?)",
                          (user_id, username, first_name, utcnow().isoformat(), referrer_id))
                created = True
        return self.get_user(user_id), created

    def update_user(self, user_id: int, **fields) -> None:
        if not fields:
            return
        values = []
        for v in fields.values():
            if isinstance(v, datetime):
                v = v.isoformat()
            elif isinstance(v, bool):
                v = int(v)
            values.append(v)
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as c:
            c.execute(f"UPDATE users SET {cols} WHERE id=?", (*values, user_id))

    def all_user_ids(self) -> list[int]:
        with self._conn() as c:
            return [r[0] for r in c.execute("SELECT id FROM users WHERE blocked=0")]

    def users_expiring_between(self, start: datetime, end: datetime) -> list[User]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM users WHERE blocked=0 AND sub_until > ? AND sub_until <= ?",
                             (start.isoformat(), end.isoformat())).fetchall()
        return [self._user(r) for r in rows]

    def count_referrals(self, user_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM users WHERE referrer_id=?", (user_id,)).fetchone()[0]

    def add_payment(self, user_id: int, tariff_id: str, stars: int, charge_id: str | None, demo: bool) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO payments (user_id, tariff_id, stars, charge_id, demo, created_at) VALUES (?,?,?,?,?,?)",
                      (user_id, tariff_id, stars, charge_id, int(demo), utcnow().isoformat()))

    def count_paid(self, user_id: int) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM payments WHERE user_id=? AND refunded=0", (user_id,)).fetchone()[0]

    def get_payment_by_charge(self, charge_id: str):
        with self._conn() as c:
            return c.execute("SELECT * FROM payments WHERE charge_id=?", (charge_id,)).fetchone()

    def mark_refunded(self, charge_id: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE payments SET refunded=1 WHERE charge_id=?", (charge_id,))

    def stats(self) -> dict:
        now = utcnow().isoformat()
        with self._conn() as c:
            one = lambda q, *a: c.execute(q, a).fetchone()[0]  # noqa: E731
            return {
                "users": one("SELECT COUNT(*) FROM users"),
                "active": one("SELECT COUNT(*) FROM users WHERE sub_until > ?", now),
                "trials": one("SELECT COUNT(*) FROM users WHERE trial_used=1"),
                "payments": one("SELECT COUNT(*) FROM payments WHERE demo=0 AND refunded=0"),
                "stars": one("SELECT COALESCE(SUM(stars),0) FROM payments WHERE demo=0 AND refunded=0"),
                "demo_payments": one("SELECT COUNT(*) FROM payments WHERE demo=1"),
            }


# =====================================================================
# ВЫДАЧА VPN-КЛЮЧЕЙ
# Чтобы подключить настоящую панель (3x-ui, Marzban), напишите свой класс
# с методами issue_key / revoke_key и укажите его в KEY_PROVIDER ниже.
# =====================================================================

class KeyProvider(ABC):
    @abstractmethod
    async def issue_key(self, user_id: int, location: Location, expires_at: datetime) -> str:
        """Создать или продлить доступ до expires_at и вернуть ссылку-ключ."""

    @abstractmethod
    async def revoke_key(self, user_id: int, location: Location) -> None:
        """Отключить доступ пользователя на сервере."""


class MockKeyProvider(KeyProvider):
    """Демо: генерирует правдоподобную ссылку VLESS без реального сервера."""
    _ns = uuid.UUID("6f1c2a8e-3b4d-4e5f-9a0b-1c2d3e4f5a6b")

    async def issue_key(self, user_id: int, location: Location, expires_at: datetime) -> str:
        client_id = uuid.uuid5(self._ns, f"{user_id}:{location.code}")  # при продлении ключ не меняется
        name = quote(f"{SERVICE_NAME} {location.title}")
        return (f"vless://{client_id}@{location.host}:443"
                "?type=tcp&security=reality&pbk=DEMO_PUBLIC_KEY&fp=chrome"
                f"&sni=www.microsoft.com&sid=0a1b2c3d&flow=xtls-rprx-vision#{name}")

    async def revoke_key(self, user_id: int, location: Location) -> None:
        return None


KEY_PROVIDER: KeyProvider = MockKeyProvider()


# =====================================================================
# ЛОГИКА ПОДПИСОК
# =====================================================================

@dataclass
class PaymentResult:
    user: User
    referrer: User | None


class SubscriptionService:
    def __init__(self, db: Database, provider: KeyProvider):
        self.db = db
        self.provider = provider

    def register(self, user_id: int, username: str | None, first_name: str | None,
                 start_arg: str | None = None) -> tuple[User, bool]:
        referrer_id = None
        if start_arg and start_arg.startswith("ref_") and start_arg[4:].isdigit():
            referrer_id = int(start_arg[4:])
        return self.db.upsert_user(user_id, username, first_name, referrer_id)

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
        user = self.db.get_user(user_id)
        if user.trial_used or user.is_active:
            return None
        self.db.update_user(user_id, trial_used=True)
        return await self.extend(user_id, TRIAL_DAYS)

    async def apply_payment(self, user_id: int, tariff: Tariff, charge_id: str | None, demo: bool) -> PaymentResult:
        first_payment = self.db.count_paid(user_id) == 0
        self.db.add_payment(user_id, tariff.id, tariff.stars, charge_id, demo)
        user = await self.extend(user_id, tariff.days)
        referrer = None
        if first_payment and user.referrer_id and REFERRAL_BONUS_DAYS > 0 and self.db.get_user(user.referrer_id):
            referrer = await self.extend(user.referrer_id, REFERRAL_BONUS_DAYS)
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
        now = utcnow()
        users = self.db.users_expiring_between(now, now + timedelta(hours=24))
        return [u for u in users if u.reminded_for != u.sub_until.isoformat()]

    def mark_reminded(self, user: User) -> None:
        self.db.update_user(user.id, reminded_for=user.sub_until.isoformat())


# =====================================================================
# ТЕКСТЫ
# =====================================================================

def fmt_date(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def days_left(dt: datetime) -> int:
    seconds = (dt - utcnow()).total_seconds()
    return max(0, int(-(-seconds // 86400)))


def text_welcome(name: str | None) -> str:
    hello = f"Привет, {escape(name)}! 👋" if name else "Привет! 👋"
    trial = (f"\n\n🎁 Новым пользователям — <b>{TRIAL_DAYS} дня бесплатно</b>, без привязки карты."
             if TRIAL_DAYS else "")
    return (f"{hello}\n\n<b>{escape(SERVICE_NAME)}</b> — быстрый и стабильный VPN на протоколе VLESS Reality.\n\n"
            "⚡️ Высокая скорость, видео в 4K без буферизации\n"
            "🔒 Без логов, трафик полностью шифруется\n"
            "📱 iPhone, Android, Windows, macOS\n"
            "🌍 Серверы в Нидерландах, Германии и Финляндии" + trial)


def text_tariffs() -> str:
    lines = [f"• {t.title} — <b>{t.stars} ⭐</b>" + (f" ({t.badge})" if t.badge else "") for t in TARIFFS]
    return ("💳 <b>Выберите тариф</b>\n\n" + "\n".join(lines) +
            "\n\nОплата через Telegram Stars — звёзды можно купить прямо в Telegram. "
            "Если подписка уже есть, срок прибавится к текущему.")


def text_profile(user: User, referrals: int) -> str:
    if user.is_active:
        status = f"✅ <b>Активна</b> до {fmt_date(user.sub_until)}\nОсталось дней: <b>{days_left(user.sub_until)}</b>"
    elif user.sub_until:
        status = f"⛔️ <b>Закончилась</b> {fmt_date(user.sub_until)}"
    else:
        status = "⚪️ <b>Нет подписки</b>"
    return (f"👤 <b>Мой профиль</b>\n\nID: <code>{user.id}</code>\nПодписка: {status}\n"
            f"Локация: {get_location(user.location).title}\nПриглашено друзей: {referrals}")


def text_key(user: User) -> str:
    return ("🔑 <b>Ваш ключ доступа</b>\n\n"
            f"Локация: {get_location(user.location).title}\n"
            f"Действует до: <b>{fmt_date(user.sub_until)}</b>\n\n"
            "Нажмите на ключ, чтобы скопировать, и добавьте его в приложение "
            "(раздел «📲 Как подключить»):\n\n"
            f"<code>{escape(user.vpn_key)}</code>")


def text_payment_success(user: User, tariff_title: str, demo: bool) -> str:
    note = "\n\n🧪 <i>Это демо-оплата: звёзды не списывались.</i>" if demo else ""
    return (f"🎉 Оплата прошла! Тариф «{tariff_title}» активирован.\n"
            f"Подписка действует до <b>{fmt_date(user.sub_until)}</b>.{note}")


def text_trial_started(user: User) -> str:
    return f"🎁 Пробный период активирован на {TRIAL_DAYS} дн.\nДоступ открыт до <b>{fmt_date(user.sub_until)}</b>."


TEXT_TRIAL_UNAVAILABLE = ("Пробный период уже использован или у вас есть активная подписка. "
                          "Продлить доступ можно в разделе «💳 Купить подписку».")
TEXT_NO_KEY = "У вас пока нет активной подписки. Оформите её или включите пробный период 👇"
TEXT_HELP_MENU = "📲 <b>Как подключить VPN</b>\n\nВыберите ваше устройство:"


def text_referral(link: str, referrals: int) -> str:
    return ("👥 <b>Пригласите друга — получите бонус</b>\n\n"
            f"Когда друг оплатит первую подписку по вашей ссылке, вам начислится "
            f"<b>+{REFERRAL_BONUS_DAYS} дней</b> бесплатно.\n\n"
            f"Ваша ссылка:\n<code>{link}</code>\n\nПриглашено: {referrals}")


def text_referral_bonus(user: User) -> str:
    return (f"🎉 Ваш друг оформил подписку! Вам начислено +{REFERRAL_BONUS_DAYS} дней.\n"
            f"Подписка действует до <b>{fmt_date(user.sub_until)}</b>.")


def text_reminder(user: User) -> str:
    return f"⏳ Подписка закончится {fmt_date(user.sub_until)}.\nПродлите заранее, чтобы VPN не отключился."


INSTRUCTIONS = {
    "ios": ("🍏 <b>iPhone / iPad</b>\n\n"
            "1. Установите приложение <b>v2RayTun</b> или <b>Streisand</b> из App Store.\n"
            "2. В боте откройте «🔑 Мой ключ» и нажмите на ключ — он скопируется.\n"
            "3. В приложении нажмите «+» → «Импорт из буфера обмена».\n"
            "4. Включите подключение и разрешите добавить VPN-конфигурацию."),
    "android": ("🤖 <b>Android</b>\n\n"
                "1. Установите <b>v2rayNG</b> или <b>Hiddify</b> из Google Play.\n"
                "2. Скопируйте ключ в разделе «🔑 Мой ключ».\n"
                "3. В приложении нажмите «+» → «Импорт из буфера обмена».\n"
                "4. Нажмите кнопку подключения внизу экрана."),
    "windows": ("🪟 <b>Windows</b>\n\n"
                "1. Скачайте <b>Hiddify</b> или <b>v2rayN</b> с официального GitHub проекта.\n"
                "2. Скопируйте ключ в разделе «🔑 Мой ключ».\n"
                "3. В приложении выберите «Добавить профиль» → «Из буфера обмена».\n"
                "4. Нажмите «Подключиться»."),
    "macos": ("💻 <b>macOS</b>\n\n"
              "1. Установите <b>Hiddify</b> или <b>V2Box</b> из App Store.\n"
              "2. Скопируйте ключ в разделе «🔑 Мой ключ».\n"
              "3. Добавьте профиль из буфера обмена.\n"
              "4. Включите подключение."),
}


def text_support() -> str:
    return (f"💬 <b>Поддержка</b>\n\nПишите: @{escape(SUPPORT_USERNAME)}\n"
            "Отвечаем ежедневно с 9:00 до 23:00 (МСК).")


TEXT_TERMS = ("📄 <b>Условия использования</b>\n\n"
              "1. Сервис предоставляет доступ к VPN на оплаченный срок.\n"
              "2. Оплата производится в Telegram Stars. Подписка активируется сразу после оплаты.\n"
              "3. Если сервис не работает по нашей вине, мы вернём звёзды — напишите в /paysupport.\n"
              "4. Запрещено использовать сервис для действий, нарушающих закон.")


def text_paysupport() -> str:
    return ("💬 <b>Вопросы по оплате</b>\n\n"
            f"Если возникла проблема с оплатой или нужен возврат, напишите @{escape(SUPPORT_USERNAME)} "
            "и приложите ID платежа из чека Telegram. Ответим в течение 24 часов.")


# =====================================================================
# КНОПКИ
# =====================================================================

def kb_main(user: User) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    show_trial = not user.trial_used and not user.is_active and TRIAL_DAYS > 0
    kb.button(text="💳 Купить подписку", callback_data="buy")
    if show_trial:
        kb.button(text=f"🎁 Попробовать {TRIAL_DAYS} дня бесплатно", callback_data="trial")
    kb.button(text="🔑 Мой ключ", callback_data="key")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="📲 Как подключить", callback_data="help")
    kb.button(text="👥 Пригласить друга", callback_data="ref")
    kb.button(text="💬 Поддержка", callback_data="support")
    kb.adjust(*((1, 1, 2, 2, 1) if show_trial else (1, 2, 2, 1)))
    return kb.as_markup()


def kb_back(to: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data=to)]])


def kb_tariffs() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in TARIFFS:
        kb.button(text=t.button_text, callback_data=f"tariff:{t.id}")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def kb_pay(tariff: Tariff) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⭐ Оплатить {tariff.stars} Stars", callback_data=f"pay:{tariff.id}")
    if DEMO_PAYMENTS:
        kb.button(text="🧪 Демо-оплата (без списания)", callback_data=f"demopay:{tariff.id}")
    kb.button(text="← К тарифам", callback_data="buy")
    kb.adjust(1)
    return kb.as_markup()


def kb_after_payment() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Получить ключ", callback_data="key")
    kb.button(text="📲 Как подключить", callback_data="help")
    kb.button(text="🏠 Главное меню", callback_data="menu")
    kb.adjust(1, 2)
    return kb.as_markup()


def kb_key_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Сменить локацию", callback_data="locations")
    kb.button(text="📲 Как подключить", callback_data="help")
    kb.button(text="💳 Продлить", callback_data="buy")
    kb.button(text="🏠 Меню", callback_data="menu")
    kb.adjust(1, 1, 2)
    return kb.as_markup()


def kb_no_key(user: User) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Купить подписку", callback_data="buy")
    if not user.trial_used and TRIAL_DAYS > 0:
        kb.button(text="🎁 Пробный период", callback_data="trial")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def kb_locations(current: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for loc in LOCATIONS:
        kb.button(text=loc.title + (" ✓" if loc.code == current else ""), callback_data=f"loc:{loc.code}")
    kb.button(text="← Назад", callback_data="key")
    kb.adjust(1)
    return kb.as_markup()


def kb_devices() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍏 iPhone / iPad", callback_data="dev:ios")
    kb.button(text="🤖 Android", callback_data="dev:android")
    kb.button(text="🪟 Windows", callback_data="dev:windows")
    kb.button(text="💻 macOS", callback_data="dev:macos")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def kb_profile() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Мой ключ", callback_data="key")
    kb.button(text="💳 Продлить", callback_data="buy")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(2, 1)
    return kb.as_markup()


# =====================================================================
# ВСПОМОГАТЕЛЬНОЕ
# =====================================================================

async def show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Показывает экран в том же сообщении; сообщение с QR-кодом заменяется новым."""
    message = callback.message
    if not message.photo:
        try:
            await message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


def qr_png(data: str) -> BufferedInputFile:
    buf = BytesIO()
    qrcode.make(data, box_size=8, border=2).save(buf, format="PNG")
    return BufferedInputFile(buf.getvalue(), filename="vpn-key.png")


# =====================================================================
# ХЕНДЛЕРЫ: ПОЛЬЗОВАТЕЛЬ
# =====================================================================

user_router = Router(name="user")


@user_router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, service: SubscriptionService):
    user, _ = service.register(message.from_user.id, message.from_user.username,
                               message.from_user.first_name, command.args)
    await message.answer(text_welcome(message.from_user.first_name), reply_markup=kb_main(user))


@user_router.message(Command("menu"))
async def cmd_menu(message: Message, service: SubscriptionService):
    user, _ = service.register(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(text_welcome(message.from_user.first_name), reply_markup=kb_main(user))


@user_router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    await show(callback, text_welcome(callback.from_user.first_name), kb_main(user))
    await callback.answer()


@user_router.callback_query(F.data == "trial")
async def cb_trial(callback: CallbackQuery, service: SubscriptionService):
    user = await service.start_trial(callback.from_user.id)
    if user is None:
        await callback.answer(TEXT_TRIAL_UNAVAILABLE, show_alert=True)
        return
    await show(callback, text_trial_started(user), kb_after_payment())
    await callback.answer("Пробный период активирован 🎁")


async def send_key(chat_message: Message, service: SubscriptionService, user_id: int) -> None:
    user = service.db.get_user(user_id)
    if not user.is_active or not user.vpn_key:
        await chat_message.answer(TEXT_NO_KEY, reply_markup=kb_no_key(user))
        return
    await chat_message.answer_photo(qr_png(user.vpn_key), caption=text_key(user), reply_markup=kb_key_actions())


@user_router.callback_query(F.data == "key")
async def cb_key(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    if not user.is_active or not user.vpn_key:
        await show(callback, TEXT_NO_KEY, kb_no_key(user))
    else:
        await send_key(callback.message, service, user.id)
    await callback.answer()


@user_router.message(Command("key"))
async def cmd_key(message: Message, service: SubscriptionService):
    service.register(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await send_key(message, service, message.from_user.id)


@user_router.callback_query(F.data == "locations")
async def cb_locations(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    await show(callback, "🌍 <b>Выберите локацию сервера</b>\n\nПосле смены локации бот пришлёт новый ключ.",
               kb_locations(user.location or get_location(None).code))
    await callback.answer()


@user_router.callback_query(F.data.startswith("loc:"))
async def cb_set_location(callback: CallbackQuery, service: SubscriptionService):
    code = callback.data.split(":", 1)[1]
    user = await service.change_location(callback.from_user.id, code)
    await callback.answer(f"Локация: {get_location(code).title}")
    if user.is_active:
        await send_key(callback.message, service, user.id)
    else:
        await show(callback, TEXT_NO_KEY, kb_no_key(user))


@user_router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    await show(callback, text_profile(user, service.db.count_referrals(user.id)), kb_profile())
    await callback.answer()


@user_router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await show(callback, TEXT_HELP_MENU, kb_devices())
    await callback.answer()


@user_router.callback_query(F.data.startswith("dev:"))
async def cb_device(callback: CallbackQuery):
    await show(callback, INSTRUCTIONS.get(callback.data.split(":", 1)[1], TEXT_HELP_MENU), kb_back("help"))
    await callback.answer()


@user_router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(TEXT_HELP_MENU, reply_markup=kb_devices())


@user_router.callback_query(F.data == "ref")
async def cb_ref(callback: CallbackQuery, bot: Bot, service: SubscriptionService):
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"
    await show(callback, text_referral(link, service.db.count_referrals(callback.from_user.id)), kb_back())
    await callback.answer()


@user_router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    await show(callback, text_support(), kb_back())
    await callback.answer()


@user_router.message(Command("support"))
async def cmd_support(message: Message):
    await message.answer(text_support())


@user_router.message(Command("terms"))
async def cmd_terms(message: Message):
    await message.answer(TEXT_TERMS)


@user_router.message(Command("paysupport"))
async def cmd_paysupport(message: Message):
    await message.answer(text_paysupport())


# =====================================================================
# ХЕНДЛЕРЫ: ОПЛАТА
# =====================================================================

pay_router = Router(name="payments")


@pay_router.callback_query(F.data == "buy")
async def cb_buy(callback: CallbackQuery):
    await show(callback, text_tariffs(), kb_tariffs())
    await callback.answer()


@pay_router.callback_query(F.data.startswith("tariff:"))
async def cb_tariff(callback: CallbackQuery):
    tariff = get_tariff(callback.data.split(":", 1)[1])
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    demo = ("\n\n🧪 Бот работает в демо-режиме: можно оплатить по-настоящему или нажать "
            "«Демо-оплата», чтобы пройти сценарий без списания звёзд.") if DEMO_PAYMENTS else ""
    await show(callback, f"Тариф <b>{tariff.title}</b> — {tariff.stars} ⭐\n"
                         f"Доступ на {tariff.days} дней ко всем локациям.{demo}", kb_pay(tariff))
    await callback.answer()


@pay_router.callback_query(F.data.startswith("pay:"))
async def cb_pay(callback: CallbackQuery, bot: Bot):
    tariff = get_tariff(callback.data.split(":", 1)[1])
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    # Telegram Stars: валюта XTR, provider_token не нужен
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"{SERVICE_NAME}: {tariff.title}",
        description=f"Доступ к VPN на {tariff.days} дней, все локации.",
        payload=f"sub:{tariff.id}",
        currency="XTR",
        prices=[LabeledPrice(label=tariff.title, amount=tariff.stars)],
    )
    await callback.answer()


@pay_router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload or ""
    tariff = get_tariff(payload.split(":", 1)[1]) if payload.startswith("sub:") else None
    if tariff is None or query.total_amount != tariff.stars:
        await query.answer(ok=False, error_message="Тариф изменился, выберите его заново.")
        return
    await query.answer(ok=True)


async def finish_payment(message: Message, bot: Bot, service: SubscriptionService, user_id: int,
                         tariff_id: str, charge_id: str | None, demo: bool) -> None:
    tariff = get_tariff(tariff_id)
    result = await service.apply_payment(user_id, tariff, charge_id, demo)
    await message.answer(text_payment_success(result.user, tariff.title, demo), reply_markup=kb_after_payment())
    if result.referrer:
        try:
            await bot.send_message(result.referrer.id, text_referral_bonus(result.referrer))
        except Exception as e:
            log.warning("Не удалось уведомить реферера %s: %s", result.referrer.id, e)
    for admin_id in ADMIN_IDS:
        try:
            mark = "🧪 демо" if demo else f"{tariff.stars} ⭐"
            await bot.send_message(admin_id, f"💰 Новая оплата: {tariff.title} ({mark}) от <code>{user_id}</code>")
        except Exception:
            pass


@pay_router.message(F.successful_payment)
async def successful_payment(message: Message, bot: Bot, service: SubscriptionService):
    sp = message.successful_payment
    service.register(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await finish_payment(message, bot, service, message.from_user.id, sp.invoice_payload.split(":", 1)[1],
                         sp.telegram_payment_charge_id, demo=False)


@pay_router.callback_query(F.data.startswith("demopay:"))
async def cb_demo_pay(callback: CallbackQuery, bot: Bot, service: SubscriptionService):
    if not DEMO_PAYMENTS:
        await callback.answer("Демо-оплата отключена", show_alert=True)
        return
    tariff = get_tariff(callback.data.split(":", 1)[1])
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer("Демо-оплата принята 🧪")
    await finish_payment(callback.message, bot, service, callback.from_user.id, tariff.id, None, demo=True)


# =====================================================================
# ХЕНДЛЕРЫ: АДМИНИСТРАТОР (только ID из ADMIN_IDS)
# =====================================================================

admin_router = Router(name="admin")
admin_router.message.filter(F.from_user.id.in_(ADMIN_IDS))

ADMIN_HELP = ("🛠 <b>Админ-панель</b>\n\n"
              "/stats — статистика\n"
              "/give &lt;user_id&gt; &lt;дней&gt; — начислить дни\n"
              "/user &lt;user_id&gt; — информация о пользователе\n"
              "/refund &lt;charge_id&gt; — вернуть звёзды за платёж\n"
              "/broadcast &lt;текст&gt; — рассылка всем пользователям")


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message):
    await message.answer(ADMIN_HELP)


@admin_router.message(Command("stats"))
async def cmd_stats(message: Message, service: SubscriptionService):
    s = service.db.stats()
    await message.answer("📊 <b>Статистика</b>\n\n"
                         f"Пользователей: <b>{s['users']}</b>\n"
                         f"Активных подписок: <b>{s['active']}</b>\n"
                         f"Взяли пробный период: {s['trials']}\n"
                         f"Оплат: <b>{s['payments']}</b> на <b>{s['stars']} ⭐</b>\n"
                         f"Демо-оплат: {s['demo_payments']}")


@admin_router.message(Command("give"))
async def cmd_give(message: Message, command: CommandObject, bot: Bot, service: SubscriptionService):
    parts = (command.args or "").split()
    if len(parts) != 2 or not all(p.lstrip("-").isdigit() for p in parts):
        await message.answer("Формат: /give &lt;user_id&gt; &lt;дней&gt;")
        return
    user_id, days = int(parts[0]), int(parts[1])
    if not service.db.get_user(user_id):
        await message.answer("Пользователь не найден — он должен хотя бы раз запустить бота.")
        return
    user = await service.extend(user_id, days)
    await message.answer(f"Готово. Подписка <code>{user_id}</code> до {fmt_date(user.sub_until)}.")
    try:
        await bot.send_message(user_id, f"🎁 Вам начислено {days} дн. Подписка до {fmt_date(user.sub_until)}.")
    except Exception:
        pass


@admin_router.message(Command("user"))
async def cmd_user(message: Message, command: CommandObject, service: SubscriptionService):
    arg = (command.args or "").strip()
    user = service.db.get_user(int(arg)) if arg.isdigit() else None
    if not user:
        await message.answer("Формат: /user &lt;user_id&gt;")
        return
    until = fmt_date(user.sub_until) if user.sub_until else "—"
    await message.answer(f"👤 <code>{user.id}</code> @{user.username or '—'}\n"
                         f"Подписка до: {until} ({'активна' if user.is_active else 'нет'})\n"
                         f"Пробный период: {'да' if user.trial_used else 'нет'}\n"
                         f"Оплат: {service.db.count_paid(user.id)}, приглашено: {service.db.count_referrals(user.id)}")


@admin_router.message(Command("refund"))
async def cmd_refund(message: Message, command: CommandObject, bot: Bot, service: SubscriptionService):
    charge_id = (command.args or "").strip()
    payment = service.db.get_payment_by_charge(charge_id) if charge_id else None
    if not payment:
        await message.answer("Платёж не найден. Формат: /refund &lt;charge_id&gt;")
        return
    if payment["refunded"]:
        await message.answer("Этот платёж уже возвращён.")
        return
    await bot.refund_star_payment(user_id=payment["user_id"], telegram_payment_charge_id=charge_id)
    await service.refund(charge_id)
    await message.answer(f"Возврат {payment['stars']} ⭐ выполнен, дни списаны.")


@admin_router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, command: CommandObject, bot: Bot, service: SubscriptionService):
    text = (command.args or "").strip()
    if not text:
        await message.answer("Формат: /broadcast &lt;текст&gt;")
        return
    sent = failed = 0
    for user_id in service.db.all_user_ids():
        try:
            await bot.send_message(user_id, text)
            sent += 1
        except TelegramForbiddenError:
            service.db.update_user(user_id, blocked=True)
            failed += 1
        except Exception as e:
            log.warning("broadcast %s: %s", user_id, e)
            failed += 1
        await asyncio.sleep(0.05)  # ~20 сообщений в секунду, в пределах лимитов Telegram
    await message.answer(f"Рассылка завершена: доставлено {sent}, не доставлено {failed}.")


# =====================================================================
# НАПОМИНАНИЯ И ЗАПУСК
# =====================================================================

RENEW_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Продлить", callback_data="buy")]])


async def reminder_loop(bot: Bot, service: SubscriptionService) -> None:
    """Раз в 30 минут предупреждает тех, у кого подписка закончится в ближайшие 24 часа."""
    while True:
        try:
            for user in service.due_reminders():
                try:
                    await bot.send_message(user.id, text_reminder(user), reply_markup=RENEW_KB)
                except TelegramForbiddenError:
                    service.db.update_user(user.id, blocked=True)
                service.mark_reminded(user)
                await asyncio.sleep(0.05)
        except Exception:
            log.exception("Ошибка в напоминаниях")
        await asyncio.sleep(REMINDER_CHECK_SECONDS)


COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="key", description="Мой ключ"),
    BotCommand(command="help", description="Как подключить"),
    BotCommand(command="support", description="Поддержка"),
    BotCommand(command="paysupport", description="Вопросы по оплате"),
    BotCommand(command="terms", description="Условия использования"),
]


def build_dispatcher(service: SubscriptionService) -> Dispatcher:
    dp = Dispatcher()
    dp["service"] = service  # попадает в хендлеры как аргумент service
    dp.include_routers(admin_router, pay_router, user_router)
    return dp


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise SystemExit("Не задан BOT_TOKEN. Впишите токен от @BotFather в блок НАСТРОЙКИ или в файл .env.")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    service = SubscriptionService(Database(DB_PATH), KEY_PROVIDER)
    dp = build_dispatcher(service)

    await bot.set_my_commands(COMMANDS)
    reminders = asyncio.create_task(reminder_loop(bot, service))
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
