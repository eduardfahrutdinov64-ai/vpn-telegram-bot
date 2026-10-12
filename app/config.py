"""Настройки бота. Все значения берутся из файла .env (см. .env.example)."""
import os
from dataclasses import dataclass, field
from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "да")


def _ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


def _tz(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:  # на Windows нет базы часовых поясов без пакета tzdata — берём МСК (UTC+3)
        return timezone(timedelta(hours=3), "MSK")


@dataclass(frozen=True)
class Location:
    code: str
    title: str
    host: str


@dataclass(frozen=True)
class Config:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    admin_ids: set[int] = field(default_factory=lambda: _ids("ADMIN_IDS"))
    # Демо-режим: рядом с оплатой Stars появляется кнопка «Демо-оплата» без списания звёзд
    demo_payments: bool = field(default_factory=lambda: _bool("DEMO_PAYMENTS", True))
    trial_days: int = field(default_factory=lambda: int(os.getenv("TRIAL_DAYS", "3")))
    referral_bonus_days: int = field(default_factory=lambda: int(os.getenv("REFERRAL_BONUS_DAYS", "7")))
    support_username: str = field(default_factory=lambda: os.getenv("SUPPORT_USERNAME", "support").lstrip("@"))
    service_name: str = field(default_factory=lambda: os.getenv("SERVICE_NAME", "NovaVPN"))
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "vpn_bot.sqlite3"))
    tz: tzinfo = field(default_factory=lambda: _tz(os.getenv("TZ_NAME", "Europe/Moscow")))


# Локации серверов. Для реального сервиса замените host на адреса своих серверов.
LOCATIONS: list[Location] = [
    Location("nl", "🇳🇱 Нидерланды", "nl.example-vpn.com"),
    Location("de", "🇩🇪 Германия", "de.example-vpn.com"),
    Location("fi", "🇫🇮 Финляндия", "fi.example-vpn.com"),
]


def get_location(code: str | None) -> Location:
    for loc in LOCATIONS:
        if loc.code == code:
            return loc
    return LOCATIONS[0]


config = Config()
