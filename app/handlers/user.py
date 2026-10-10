"""Основные сценарии пользователя: меню, пробный период, ключ, локации, инструкции, рефералы."""
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app import texts
from app.config import get_location
from app.handlers.common import qr_png, show
from app.services import SubscriptionService

router = Router(name="user")


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, service: SubscriptionService):
    user, _ = service.register(message.from_user.id, message.from_user.username,
                               message.from_user.first_name, command.args)
    await message.answer(texts.welcome(message.from_user.first_name), reply_markup=kb.main_menu(user))


@router.message(Command("menu"))
async def cmd_menu(message: Message, service: SubscriptionService):
    user, _ = service.register(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await message.answer(texts.welcome(message.from_user.first_name), reply_markup=kb.main_menu(user))


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    await show(callback, texts.welcome(callback.from_user.first_name), kb.main_menu(user))
    await callback.answer()


# ---------- пробный период ----------
@router.callback_query(F.data == "trial")
async def cb_trial(callback: CallbackQuery, service: SubscriptionService):
    user = await service.start_trial(callback.from_user.id)
    if user is None:
        await callback.answer(texts.TRIAL_UNAVAILABLE, show_alert=True)
        return
    await show(callback, texts.trial_started(user), kb.after_payment())
    await callback.answer("Пробный период активирован 🎁")


# ---------- ключ ----------
async def send_key(chat_message: Message, service: SubscriptionService, user_id: int) -> None:
    user = service.db.get_user(user_id)
    if not user.is_active or not user.vpn_key:
        await chat_message.answer(texts.NO_KEY, reply_markup=kb.no_key(user))
        return
    await chat_message.answer_photo(qr_png(user.vpn_key), caption=texts.key_message(user),
                                    reply_markup=kb.key_actions())


@router.callback_query(F.data == "key")
async def cb_key(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    if not user.is_active or not user.vpn_key:
        await show(callback, texts.NO_KEY, kb.no_key(user))
    else:
        await send_key(callback.message, service, user.id)
    await callback.answer()


@router.message(Command("key"))
async def cmd_key(message: Message, service: SubscriptionService):
    service.register(message.from_user.id, message.from_user.username, message.from_user.first_name)
    await send_key(message, service, message.from_user.id)


# ---------- локации ----------
@router.callback_query(F.data == "locations")
async def cb_locations(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    await show(callback, "🌍 <b>Выберите локацию сервера</b>\n\nПосле смены локации бот пришлёт новый ключ.",
               kb.locations(user.location or get_location(None).code))
    await callback.answer()


@router.callback_query(F.data.startswith("loc:"))
async def cb_set_location(callback: CallbackQuery, service: SubscriptionService):
    code = callback.data.split(":", 1)[1]
    user = await service.change_location(callback.from_user.id, code)
    await callback.answer(f"Локация: {get_location(code).title}")
    if user.is_active:
        await send_key(callback.message, service, user.id)
    else:
        await show(callback, texts.NO_KEY, kb.no_key(user))


# ---------- профиль ----------
@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery, service: SubscriptionService):
    user = service.db.get_user(callback.from_user.id)
    await show(callback, texts.profile(user, service.db.count_referrals(user.id)), kb.profile())
    await callback.answer()


# ---------- инструкции ----------
@router.callback_query(F.data == "help")
async def cb_help(callback: CallbackQuery):
    await show(callback, texts.HELP_MENU, kb.devices())
    await callback.answer()


@router.callback_query(F.data.startswith("dev:"))
async def cb_device(callback: CallbackQuery):
    text = texts.INSTRUCTIONS.get(callback.data.split(":", 1)[1], texts.HELP_MENU)
    await show(callback, text, kb.back("help"))
    await callback.answer()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(texts.HELP_MENU, reply_markup=kb.devices())


# ---------- рефералы ----------
@router.callback_query(F.data == "ref")
async def cb_ref(callback: CallbackQuery, bot: Bot, service: SubscriptionService):
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"
    await show(callback, texts.referral(link, service.db.count_referrals(callback.from_user.id)), kb.back())
    await callback.answer()


# ---------- поддержка и условия ----------
@router.callback_query(F.data == "support")
async def cb_support(callback: CallbackQuery):
    await show(callback, texts.support(), kb.back())
    await callback.answer()


@router.message(Command("support"))
async def cmd_support(message: Message):
    await message.answer(texts.support())


@router.message(Command("terms"))
async def cmd_terms(message: Message):
    await message.answer(texts.TERMS)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message):
    await message.answer(texts.paysupport())
