"""Фоновая задача: напоминает о скором окончании подписки."""
import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app import texts
from app.services import SubscriptionService

log = logging.getLogger(__name__)
CHECK_EVERY_SECONDS = 30 * 60

RENEW_KB = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💳 Продлить", callback_data="buy")]])


async def reminder_loop(bot: Bot, service: SubscriptionService) -> None:
    while True:
        try:
            for user in service.due_reminders():
                try:
                    await bot.send_message(user.id, texts.reminder(user), reply_markup=RENEW_KB)
                except TelegramForbiddenError:
                    service.db.update_user(user.id, blocked=True)
                service.mark_reminded(user)
                await asyncio.sleep(0.05)
        except Exception:
            log.exception("Ошибка в напоминаниях")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
