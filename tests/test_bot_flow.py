"""Сквозной тест хендлеров через диспетчер aiogram с подставной сессией (без сети).
Запуск: python -m unittest tests.test_bot_flow   (нужны установленные зависимости)"""
import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timezone

os.environ["ADMIN_IDS"] = "900"
os.environ["DEMO_PAYMENTS"] = "true"

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402
from aiogram.methods import (AnswerCallbackQuery, AnswerPreCheckoutQuery, DeleteMessage,  # noqa: E402
                             EditMessageText, GetMe, RefundStarPayment, SendInvoice, SendMessage,
                             SendPhoto, TelegramMethod)
from aiogram.types import (CallbackQuery, Chat, Message, PreCheckoutQuery, SuccessfulPayment,  # noqa: E402
                           Update, User)

from app.db import Database  # noqa: E402
from app.handlers import admin, payments, user  # noqa: E402
from app.services import SubscriptionService  # noqa: E402
from app.vpn.mock import MockKeyProvider  # noqa: E402

NOW = datetime.now(timezone.utc)
BOT_USER = User(id=1, is_bot=True, first_name="NovaVPN", username="novavpn_bot")


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls: list[TelegramMethod] = []
        self._mid = 100

    def _msg(self, chat_id, text=None, photo=False):
        self._mid += 1
        return Message(message_id=self._mid, date=NOW, chat=Chat(id=chat_id, type="private"),
                       from_user=BOT_USER, text=text,
                       photo=[{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}] if photo else None)

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, (SendMessage, SendInvoice)):
            return self._msg(method.chat_id, getattr(method, "text", None))
        if isinstance(method, SendPhoto):
            return self._msg(method.chat_id, photo=True)
        if isinstance(method, EditMessageText):
            return self._msg(method.chat_id, method.text)
        return True

    async def stream_content(self, *a, **kw):  # pragma: no cover
        yield b""

    async def close(self):
        pass


class BotFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        self.service = SubscriptionService(Database(self.path), MockKeyProvider())
        self.dp = Dispatcher()
        self.dp["service"] = self.service
        self.dp.include_routers(admin.router, payments.router, user.router)
        self.uid = 0

    async def asyncTearDown(self):
        os.remove(self.path)
        # роутеры — модульные синглтоны, отвязываем их, чтобы следующий тест мог подключить заново
        for r in (admin.router, payments.router, user.router):
            r._parent_router = None

    def _user(self, uid):
        return User(id=uid, is_bot=False, first_name="Иван", username=f"user{uid}")

    async def send(self, uid, text):
        self.uid += 1
        msg = Message(message_id=self.uid, date=NOW, chat=Chat(id=uid, type="private"),
                      from_user=self._user(uid), text=text)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, message=msg))

    async def click(self, uid, data, photo=False):
        self.uid += 1
        msg = Message(message_id=50, date=NOW, chat=Chat(id=uid, type="private"), from_user=BOT_USER, text="x",
                      photo=[{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}] if photo else None)
        cq = CallbackQuery(id=str(self.uid), from_user=self._user(uid), chat_instance="c", message=msg, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, callback_query=cq))

    def last(self, kind):
        return next(c for c in reversed(self.session.calls) if isinstance(c, kind))

    def texts(self):
        out = []
        for c in self.session.calls:
            out.append(getattr(c, "text", None) or getattr(c, "caption", None) or "")
        return "\n".join(out)

    def buttons(self, call):
        return [b.callback_data for row in call.reply_markup.inline_keyboard for b in row]

    async def test_full_user_journey(self):
        # старт и меню
        await self.send(10, "/start")
        start = self.last(SendMessage)
        self.assertIn("Иван", start.text)
        self.assertIn("trial", self.buttons(start))

        # без подписки ключа нет
        await self.click(10, "key")
        self.assertIn("нет активной подписки", self.last(EditMessageText).text)

        # пробный период -> ключ с QR
        await self.click(10, "trial")
        self.assertIn("Пробный период активирован", self.last(EditMessageText).text)
        await self.click(10, "key")
        photo = self.last(SendPhoto)
        self.assertIn("vless://", photo.caption)
        self.assertIn("locations", self.buttons(photo))

        # повторный пробный период недоступен
        await self.click(10, "trial")
        self.assertTrue(self.last(AnswerCallbackQuery).show_alert)

        # смена локации с экрана ключа (сообщение-фото)
        await self.click(10, "locations", photo=True)
        await self.click(10, "loc:de")
        self.assertIn("de.example-vpn.com", self.last(SendPhoto).caption)

        # тарифы -> счёт Stars
        await self.click(10, "buy", photo=True)
        self.assertIn("Выберите тариф", self.last(SendMessage).text)
        self.assertIsInstance(self.session.calls[-2], DeleteMessage)  # фото с QR заменено текстом
        await self.click(10, "tariff:m3")
        self.assertIn("demopay:m3", self.buttons(self.last(EditMessageText)))
        await self.click(10, "pay:m3")
        inv = self.last(SendInvoice)
        self.assertEqual((inv.currency, inv.prices[0].amount, inv.payload), ("XTR", 270, "sub:m3"))

        # pre-checkout: верная и подменённая сумма
        for amount, ok in ((270, True), (1, False)):
            self.uid += 1
            pcq = PreCheckoutQuery(id="p", from_user=self._user(10), currency="XTR",
                                   total_amount=amount, invoice_payload="sub:m3")
            await self.dp.feed_update(self.bot, Update(update_id=self.uid, pre_checkout_query=pcq))
            self.assertEqual(self.last(AnswerPreCheckoutQuery).ok, ok)

        # успешная оплата
        self.uid += 1
        sp = SuccessfulPayment(currency="XTR", total_amount=270, invoice_payload="sub:m3",
                               telegram_payment_charge_id="charge_1", provider_payment_charge_id="")
        msg = Message(message_id=self.uid, date=NOW, chat=Chat(id=10, type="private"),
                      from_user=self._user(10), successful_payment=sp)
        await self.dp.feed_update(self.bot, Update(update_id=self.uid, message=msg))
        self.assertIn("Оплата прошла", self.texts())
        self.assertIn("Новая оплата", self.texts())  # уведомление админу

        # профиль, инструкции, рефералка, поддержка
        await self.click(10, "profile")
        self.assertIn("Активна", self.last(EditMessageText).text)
        await self.click(10, "help")
        await self.click(10, "dev:ios")
        self.assertIn("iPhone", self.last(EditMessageText).text)
        await self.click(10, "ref")
        self.assertIn("t.me/novavpn_bot?start=ref_10", self.last(EditMessageText).text)
        for cmd in ("/support", "/terms", "/paysupport", "/help", "/key", "/menu"):
            await self.send(10, cmd)

    async def test_referral_and_demo_payment(self):
        await self.send(20, "/start")
        await self.send(21, "/start ref_20")
        await self.click(21, "demopay:m1")
        all_text = self.texts()
        self.assertIn("демо-оплата", all_text)
        self.assertIn("Ваш друг оформил подписку", all_text)
        self.assertTrue(self.service.db.get_user(20).is_active)

    async def test_admin_commands(self):
        await self.send(30, "/start")
        await self.send(30, "/stats")  # не админ — команда не срабатывает
        self.assertNotIn("Статистика", self.texts())

        await self.send(900, "/stats")
        self.assertIn("Статистика", self.last(SendMessage).text)
        await self.send(900, "/give 30 10")
        self.assertTrue(self.service.db.get_user(30).is_active)
        await self.send(900, "/user 30")
        self.assertIn("активна", self.last(SendMessage).text)

        await self.service.apply_payment(30, __import__("app.tariffs").tariffs.get_tariff("m1"), "ch_x", False)
        await self.send(900, "/refund ch_x")
        self.assertIsInstance(next(c for c in self.session.calls if isinstance(c, RefundStarPayment)),
                              RefundStarPayment)
        self.assertIn("Возврат 100", self.last(SendMessage).text)

        await self.send(900, "/broadcast Привет всем")
        self.assertIn("доставлено", self.last(SendMessage).text)


if __name__ == "__main__":
    unittest.main()
