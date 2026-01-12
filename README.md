# MikroTik 2FA VPN (Telegram-only, RouterOS API-only)

Проект с нуля: управление доступом к VPN **только через Telegram-бот**, без веб-интерфейса.  
Управление MikroTik выполняется **только через RouterOS API** (8728 / 8729).

## Возможности (MVP)

- Регистрация пользователей через Telegram (`/register`) с подтверждением админом
- Привязка 1+ MikroTik аккаунтов к пользователю (админ-команды)
- Запрос доступа к VPN (`/request_vpn`) → включение MikroTik аккаунта (disabled=false)
- Детект факта подключения (фоновой poll RouterOS API) → запрос 2FA подтверждения в Telegram
- Подтверждение → (опционально) включение firewall rule (по `.id` или по comment)
- Отклонение/таймаут → отключение аккаунта и попытка разорвать активное подключение
- Просмотр своих сессий и отключение

## Требования

- Python 3.11+
- Доступ к RouterOS API на MikroTik (включить `/ip service enable api` или `api-ssl`)
- Telegram bot token

## Быстрый старт

```bash
cd mikrotik-2fa-telegram-only
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp env.example .env
./venv/bin/python -m mikrotik_2fa_bot
```

## Конфигурация

См. `env.example`.

## Важные ограничения (по вашему требованию)

- Детект подключений делается **строго через User Manager sessions** (`/user-manager session`) — без PPP fallback.
- Включение/выключение пользователя делается **строго через User Manager user** (`/user-manager user`) — если пользователя нет в User Manager, бот вернёт ошибку.
- Админские команды разрешены **только из `ADMIN_CHAT_ID`**.

## Команды Telegram (план)

- Пользователь:
  - `/start`, `/help`
  - `/register`
  - `/request_vpn`
  - `/my_sessions`
  - `/disable_vpn`
- Админ:
  - `/pending`
  - `/approve <telegram_id>`
  - `/reject <telegram_id> <reason>`
  - `/bind <telegram_id> <mikrotik_username>`
  - `/unbind <telegram_id> <mikrotik_username>`
  - `/set_fw_comment <telegram_id> <comment substring>`

# 2FA-Mikrotik-TG-Only
