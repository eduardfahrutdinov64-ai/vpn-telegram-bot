"""Команды администратора. Доступны только ID из ADMIN_IDS."""
import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.config import config
from app.services import SubscriptionService
from app.texts import fmt_date

router = Router(name="admin")
router.message.filter(F.from_user.id.in_(config.admin_ids))
log = logging.getLogger(__name__)

HELP = (
    "🛠 <b>Админ-панель</b>\n\n"
    "/stats — статистика\n"
    "/give &lt;user_id&gt; &lt;дней&gt; — начислить дни\n"
    "/user &lt;user_id&gt; — информация о пользователе\n"
    "/refund &lt;charge_id&gt; — вернуть звёзды за платёж\n"
    "/broadcast &lt;текст&gt; — рассылка всем пользователям"
)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    await message.answer(HELP)


@router.message(Command("stats"))
async def cmd_stats(message: Message, service: SubscriptionService):
    s = service.db.stats()
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"Пользователей: <b>{s['users']}</b>\n"
        f"Активных подписок: <b>{s['active']}</b>\n"
        f"Взяли пробный период: {s['trials']}\n"
        f"Оплат: <b>{s['payments']}</b> на <b>{s['stars']} ⭐</b>\n"
        f"Демо-оплат: {s['demo_payments']}"
    )


@router.message(Command("give"))
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


@router.message(Command("user"))
async def cmd_user(message: Message, command: CommandObject, service: SubscriptionService):
    arg = (command.args or "").strip()
    user = service.db.get_user(int(arg)) if arg.isdigit() else None
    if not user:
        await message.answer("Формат: /user &lt;user_id&gt;")
        return
    until = fmt_date(user.sub_until) if user.sub_until else "—"
    await message.answer(
        f"👤 <code>{user.id}</code> @{user.username or '—'}\n"
        f"Подписка до: {until} ({'активна' if user.is_active else 'нет'})\n"
        f"Пробный период: {'да' if user.trial_used else 'нет'}\n"
        f"Оплат: {service.db.count_paid(user.id)}, приглашено: {service.db.count_referrals(user.id)}"
    )


@router.message(Command("refund"))
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


@router.message(Command("broadcast"))
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
