"""Покупка подписки: выбор тарифа, оплата Telegram Stars и демо-оплата."""
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery

from app import keyboards as kb
from app import texts
from app.config import config
from app.handlers.common import show
from app.services import SubscriptionService
from app.tariffs import get_tariff

router = Router(name="payments")
log = logging.getLogger(__name__)


@router.callback_query(F.data == "buy")
async def cb_buy(callback: CallbackQuery):
    await show(callback, texts.tariffs_text(), kb.tariffs())
    await callback.answer()


@router.callback_query(F.data.startswith("tariff:"))
async def cb_tariff(callback: CallbackQuery):
    tariff = get_tariff(callback.data.split(":", 1)[1])
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    demo = ("\n\n🧪 Бот работает в демо-режиме: можно оплатить по-настоящему или нажать "
            "«Демо-оплата», чтобы пройти сценарий без списания звёзд.") if config.demo_payments else ""
    await show(callback,
               f"Тариф <b>{tariff.title}</b> — {tariff.stars} ⭐\n"
               f"Доступ на {tariff.days} дней ко всем локациям.{demo}",
               kb.pay(tariff))
    await callback.answer()


@router.callback_query(F.data.startswith("pay:"))
async def cb_pay(callback: CallbackQuery, bot: Bot):
    tariff = get_tariff(callback.data.split(":", 1)[1])
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    # Для Telegram Stars валюта XTR, provider_token не нужен
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=f"{config.service_name}: {tariff.title}",
        description=f"Доступ к VPN на {tariff.days} дней, все локации.",
        payload=f"sub:{tariff.id}",
        currency="XTR",
        prices=[LabeledPrice(label=tariff.title, amount=tariff.stars)],
    )
    await callback.answer()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload or ""
    tariff = get_tariff(payload.split(":", 1)[1]) if payload.startswith("sub:") else None
    if tariff is None or query.total_amount != tariff.stars:
        await query.answer(ok=False, error_message="Тариф изменился, выберите его заново.")
        return
    await query.answer(ok=True)


async def _finish_payment(message: Message, bot: Bot, service: SubscriptionService, user_id: int,
                          tariff_id: str, charge_id: str | None, demo: bool) -> None:
    tariff = get_tariff(tariff_id)
    result = await service.apply_payment(user_id, tariff, charge_id, demo)
    await message.answer(texts.payment_success(result.user, tariff.title, demo), reply_markup=kb.after_payment())
    if result.referrer:
        try:
            await bot.send_message(result.referrer.id, texts.referral_bonus(result.referrer))
        except Exception as e:  # пользователь мог заблокировать бота
            log.warning("Не удалось уведомить реферера %s: %s", result.referrer.id, e)
    for admin_id in config.admin_ids:
        try:
            mark = "🧪 демо" if demo else f"{tariff.stars} ⭐"
            await bot.send_message(admin_id, f"💰 Новая оплата: {tariff.title} ({mark}) от <code>{user_id}</code>")
        except Exception:
            pass


@router.message(F.successful_payment)
async def successful_payment(message: Message, bot: Bot, service: SubscriptionService):
    sp = message.successful_payment
    tariff_id = sp.invoice_payload.split(":", 1)[1]
    service.register(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await _finish_payment(message, bot, service, message.from_user.id, tariff_id,
                          sp.telegram_payment_charge_id, demo=False)


@router.callback_query(F.data.startswith("demopay:"))
async def cb_demo_pay(callback: CallbackQuery, bot: Bot, service: SubscriptionService):
    if not config.demo_payments:
        await callback.answer("Демо-оплата отключена", show_alert=True)
        return
    tariff = get_tariff(callback.data.split(":", 1)[1])
    if tariff is None:
        await callback.answer("Тариф не найден", show_alert=True)
        return
    await callback.answer("Демо-оплата принята 🧪")
    await _finish_payment(callback.message, bot, service, callback.from_user.id, tariff.id, None, demo=True)
