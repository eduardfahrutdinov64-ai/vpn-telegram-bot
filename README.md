# NovaVPN Bot — Telegram-бот для продажи VPN-подписок

Демо-бот VPN-сервиса на **Python + aiogram 3**. Пользователь выбирает тариф, оплачивает его в **Telegram Stars** и сразу получает ключ VLESS с QR-кодом и инструкцией для своего устройства.

## Возможности

- 🎁 Пробный период (по умолчанию 3 дня, один раз на пользователя)
- 💳 4 тарифа с оплатой в Telegram Stars, срок суммируется с текущим
- 🧪 Демо-оплата без списания звёзд, чтобы показать сценарий заказчику
- 🔑 Выдача ключа текстом и QR-кодом
- 🌍 Выбор локации сервера (Нидерланды, Германия, Финляндия)
- 📲 Инструкции для iPhone, Android, Windows и macOS
- 👥 Реферальная программа: +7 дней пригласившему за первую оплату друга
- ⏳ Автонапоминание за 24 часа до окончания подписки
- 🛠 Админка: статистика, начисление дней, карточка пользователя, возврат звёзд, рассылка
- 📄 Команды `/terms` и `/paysupport`, которые Telegram требует от ботов с оплатой

## Быстрый запуск

1. Создайте бота у [@BotFather](https://t.me/BotFather) командой `/newbot` и скопируйте токен.
   Для оплаты в Stars подключать платёжного провайдера не нужно.
2. Установите Python 3.10 или новее и зависимости:
   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Скопируйте `.env.example` в `.env` и заполните `BOT_TOKEN` и `ADMIN_IDS`.
   Свой Telegram ID можно узнать у [@userinfobot](https://t.me/userinfobot).
4. Запустите:
   ```bash
   python bot.py
   ```

## Настройки (`.env`)

| Параметр | Что делает |
|---|---|
| `BOT_TOKEN` | токен от @BotFather |
| `ADMIN_IDS` | ID администраторов через запятую |
| `SERVICE_NAME` | название сервиса в сообщениях и ключах |
| `SUPPORT_USERNAME` | контакт поддержки (без @) |
| `DEMO_PAYMENTS` | `true` — показывать кнопку демо-оплаты; для продакшена `false` |
| `TRIAL_DAYS` | длительность пробного периода, `0` — отключить |
| `REFERRAL_BONUS_DAYS` | бонус пригласившему, дней |

Тарифы и цены задаются в `app/tariffs.py`, локации в `app/config.py`, все тексты в `app/texts.py`.

## Команды администратора

`/admin` — список команд · `/stats` — статистика · `/give <id> <дней>` — начислить дни ·
`/user <id>` — информация о пользователе · `/refund <charge_id>` — вернуть звёзды ·
`/broadcast <текст>` — рассылка

## Подключение настоящих VPN-серверов

Сейчас ключи выдаёт демо-модуль `app/vpn/mock.py`: он генерирует правдоподобную ссылку VLESS без сервера.
Чтобы бот выдавал рабочие ключи, создайте класс-наследник `KeyProvider` из `app/vpn/base.py` с двумя методами:

- `issue_key(user_id, location, expires_at)` — создать или продлить клиента в панели (3x-ui, Marzban и т.д.) и вернуть ссылку;
- `revoke_key(user_id, location)` — отключить клиента.

Затем укажите его в `app/vpn/__init__.py`. Остальной код менять не нужно.

## Запуск на сервере (Linux, systemd)

```ini
# /etc/systemd/system/vpn-bot.service
[Unit]
Description=VPN Telegram bot
After=network.target

[Service]
WorkingDirectory=/opt/vpn-bot
ExecStart=/opt/vpn-bot/.venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now vpn-bot
```

## Структура

```
bot.py                 — точка входа
app/config.py          — настройки и локации
app/tariffs.py         — тарифы
app/db.py              — база SQLite (пользователи, платежи)
app/services.py        — логика подписок (без Telegram)
app/vpn/               — выдача ключей (демо-модуль + интерфейс)
app/handlers/          — пользователь, оплата, админка
app/texts.py           — все тексты
app/keyboards.py       — кнопки
app/reminders.py       — напоминания об окончании подписки
tests/                 — тесты логики и сценариев бота
```

Тесты: `python -m unittest discover tests`
