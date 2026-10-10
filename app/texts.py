"""Все тексты бота в одном месте — их удобно править под конкретный сервис."""
from datetime import datetime
from html import escape

from app.config import config, get_location
from app.db import User, utcnow
from app.tariffs import TARIFFS


def fmt_date(dt: datetime) -> str:
    return dt.astimezone(config.tz).strftime("%d.%m.%Y %H:%M")


def days_left(dt: datetime) -> int:
    seconds = (dt - utcnow()).total_seconds()
    return max(0, int(-(-seconds // 86400)))  # округление вверх


def welcome(name: str | None) -> str:
    hello = f"Привет, {escape(name)}! 👋" if name else "Привет! 👋"
    trial = (f"\n\n🎁 Новым пользователям — <b>{config.trial_days} дня бесплатно</b>, без привязки карты."
             if config.trial_days else "")
    return (
        f"{hello}\n\n"
        f"<b>{escape(config.service_name)}</b> — быстрый и стабильный VPN на протоколе VLESS Reality.\n\n"
        "⚡️ Высокая скорость, видео в 4K без буферизации\n"
        "🔒 Без логов, трафик полностью шифруется\n"
        "📱 iPhone, Android, Windows, macOS\n"
        "🌍 Серверы в Нидерландах, Германии и Финляндии"
        f"{trial}"
    )


def tariffs_text() -> str:
    lines = [f"• {t.title} — <b>{t.stars} ⭐</b>" + (f" ({t.badge})" if t.badge else "") for t in TARIFFS]
    return (
        "💳 <b>Выберите тариф</b>\n\n" + "\n".join(lines) +
        "\n\nОплата через Telegram Stars — звёзды можно купить прямо в Telegram. "
        "Если подписка уже есть, срок прибавится к текущему."
    )


def profile(user: User, referrals: int) -> str:
    location = get_location(user.location)
    if user.is_active:
        status = (f"✅ <b>Активна</b> до {fmt_date(user.sub_until)}\n"
                  f"Осталось дней: <b>{days_left(user.sub_until)}</b>")
    elif user.sub_until:
        status = f"⛔️ <b>Закончилась</b> {fmt_date(user.sub_until)}"
    else:
        status = "⚪️ <b>Нет подписки</b>"
    return (
        "👤 <b>Мой профиль</b>\n\n"
        f"ID: <code>{user.id}</code>\n"
        f"Подписка: {status}\n"
        f"Локация: {location.title}\n"
        f"Приглашено друзей: {referrals}"
    )


def key_message(user: User) -> str:
    location = get_location(user.location)
    return (
        "🔑 <b>Ваш ключ доступа</b>\n\n"
        f"Локация: {location.title}\n"
        f"Действует до: <b>{fmt_date(user.sub_until)}</b>\n\n"
        "Нажмите на ключ, чтобы скопировать, и добавьте его в приложение "
        "(раздел «📲 Как подключить»):\n\n"
        f"<code>{escape(user.vpn_key)}</code>"
    )


def payment_success(user: User, tariff_title: str, demo: bool) -> str:
    note = "\n\n🧪 <i>Это демо-оплата: звёзды не списывались.</i>" if demo else ""
    return (f"🎉 Оплата прошла! Тариф «{tariff_title}» активирован.\n"
            f"Подписка действует до <b>{fmt_date(user.sub_until)}</b>.{note}")


def trial_started(user: User) -> str:
    return (f"🎁 Пробный период активирован на {config.trial_days} дн.\n"
            f"Доступ открыт до <b>{fmt_date(user.sub_until)}</b>.")


TRIAL_UNAVAILABLE = ("Пробный период уже использован или у вас есть активная подписка. "
                     "Продлить доступ можно в разделе «💳 Купить подписку».")

NO_KEY = "У вас пока нет активной подписки. Оформите её или включите пробный период 👇"


def referral(link: str, referrals: int) -> str:
    return (
        "👥 <b>Пригласите друга — получите бонус</b>\n\n"
        f"Когда друг оплатит первую подписку по вашей ссылке, вам начислится "
        f"<b>+{config.referral_bonus_days} дней</b> бесплатно.\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: {referrals}"
    )


def referral_bonus(user: User) -> str:
    return (f"🎉 Ваш друг оформил подписку! Вам начислено +{config.referral_bonus_days} дней.\n"
            f"Подписка действует до <b>{fmt_date(user.sub_until)}</b>.")


def reminder(user: User) -> str:
    return (f"⏳ Подписка закончится {fmt_date(user.sub_until)}.\n"
            "Продлите заранее, чтобы VPN не отключился.")


HELP_MENU = "📲 <b>Как подключить VPN</b>\n\nВыберите ваше устройство:"

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


def support() -> str:
    return (f"💬 <b>Поддержка</b>\n\nПишите: @{escape(config.support_username)}\n"
            "Отвечаем ежедневно с 9:00 до 23:00 (МСК).")


TERMS = (
    "📄 <b>Условия использования</b>\n\n"
    "1. Сервис предоставляет доступ к VPN на оплаченный срок.\n"
    "2. Оплата производится в Telegram Stars. Подписка активируется сразу после оплаты.\n"
    "3. Если сервис не работает по нашей вине, мы вернём звёзды — напишите в /paysupport.\n"
    "4. Запрещено использовать сервис для действий, нарушающих закон."
)


def paysupport() -> str:
    return ("💬 <b>Вопросы по оплате</b>\n\n"
            f"Если возникла проблема с оплатой или нужен возврат, напишите @{escape(config.support_username)} "
            "и приложите ID платежа из чека Telegram. Ответим в течение 24 часов.")
