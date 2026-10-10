"""Вспомогательные функции для хендлеров."""
from io import BytesIO

import qrcode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup


async def show(callback: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    """Показывает экран в том же сообщении. Сообщение с фото (QR-код) заменяется новым текстовым."""
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
    img = qrcode.make(data, box_size=8, border=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return BufferedInputFile(buf.getvalue(), filename="vpn-key.png")
