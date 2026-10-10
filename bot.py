"""Точка входа. Запуск: python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from app.config import config
from app.db import Database
from app.handlers import admin, payments, user
from app.reminders import reminder_loop
from app.services import SubscriptionService
from app.vpn import provider

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="key", description="Мой ключ"),
    BotCommand(command="help", description="Как подключить"),
    BotCommand(command="support", description="Поддержка"),
    BotCommand(command="paysupport", description="Вопросы по оплате"),
    BotCommand(command="terms", description="Условия использования"),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.bot_token:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от @BotFather.")

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    service = SubscriptionService(Database(config.db_path), provider)

    dp = Dispatcher()
    dp["service"] = service  # попадает в хендлеры как аргумент service
    dp.include_routers(admin.router, payments.router, user.router)

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
