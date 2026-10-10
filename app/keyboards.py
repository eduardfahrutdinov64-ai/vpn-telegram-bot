from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import LOCATIONS, config
from app.db import User
from app.tariffs import TARIFFS, Tariff


def main_menu(user: User) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    show_trial = not user.trial_used and not user.is_active and config.trial_days > 0
    kb.button(text="💳 Купить подписку", callback_data="buy")
    if show_trial:
        kb.button(text=f"🎁 Попробовать {config.trial_days} дня бесплатно", callback_data="trial")
    kb.button(text="🔑 Мой ключ", callback_data="key")
    kb.button(text="👤 Профиль", callback_data="profile")
    kb.button(text="📲 Как подключить", callback_data="help")
    kb.button(text="👥 Пригласить друга", callback_data="ref")
    kb.button(text="💬 Поддержка", callback_data="support")
    if show_trial:
        kb.adjust(1, 1, 2, 2, 1)
    else:
        kb.adjust(1, 2, 2, 1)
    return kb.as_markup()


def back(to: str = "menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="← Назад", callback_data=to)]])


def tariffs() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in TARIFFS:
        kb.button(text=t.button_text, callback_data=f"tariff:{t.id}")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def pay(tariff: Tariff) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=f"⭐ Оплатить {tariff.stars} Stars", callback_data=f"pay:{tariff.id}")
    if config.demo_payments:
        kb.button(text="🧪 Демо-оплата (без списания)", callback_data=f"demopay:{tariff.id}")
    kb.button(text="← К тарифам", callback_data="buy")
    kb.adjust(1)
    return kb.as_markup()


def after_payment() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Получить ключ", callback_data="key")
    kb.button(text="📲 Как подключить", callback_data="help")
    kb.button(text="🏠 Главное меню", callback_data="menu")
    kb.adjust(1, 2)
    return kb.as_markup()


def key_actions() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Сменить локацию", callback_data="locations")
    kb.button(text="📲 Как подключить", callback_data="help")
    kb.button(text="💳 Продлить", callback_data="buy")
    kb.button(text="🏠 Меню", callback_data="menu")
    kb.adjust(1, 1, 2)
    return kb.as_markup()


def no_key(user: User) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 Купить подписку", callback_data="buy")
    if not user.trial_used and config.trial_days:
        kb.button(text="🎁 Пробный период", callback_data="trial")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(1)
    return kb.as_markup()


def locations(current: str | None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for loc in LOCATIONS:
        mark = " ✓" if loc.code == current else ""
        kb.button(text=f"{loc.title}{mark}", callback_data=f"loc:{loc.code}")
    kb.button(text="← Назад", callback_data="key")
    kb.adjust(1)
    return kb.as_markup()


def devices() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🍏 iPhone / iPad", callback_data="dev:ios")
    kb.button(text="🤖 Android", callback_data="dev:android")
    kb.button(text="🪟 Windows", callback_data="dev:windows")
    kb.button(text="💻 macOS", callback_data="dev:macos")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def profile() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔑 Мой ключ", callback_data="key")
    kb.button(text="💳 Продлить", callback_data="buy")
    kb.button(text="← Назад", callback_data="menu")
    kb.adjust(2, 1)
    return kb.as_markup()
