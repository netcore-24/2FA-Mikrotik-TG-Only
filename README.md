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

## Запуск в Docker (docker compose)

1) Создайте `.env` (можно от `env.example`) и заполните минимум:
- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USERNAME` (без `@`)
- `MIKROTIK_HOST`, `MIKROTIK_USERNAME`, `MIKROTIK_PASSWORD`

2) Поднимите контейнер:

```bash
cd 2FA-Mikrotik-TG-Only
mkdir -p data
docker compose up -d --build
docker compose logs -f
```

SQLite БД сохраняется в `./data` (примонтирована в контейнер как `/app/data`).

## Запуск на MikroTik (RouterOS Container, arm64)

Для устройств MikroTik (RouterOS v7 + Container) нужен готовый образ в registry.
См. простую инструкцию: `routeros/README.md`.

## Установка одним скриптом (с автозапуском)

Скрипт установит зависимости, **спросит в консоли** токен бота, `ADMIN_CHAT_ID`, адрес/логин/пароль MikroTik, создаст `.env` и systemd автозапуск:

```bash
cd mikrotik-2fa-telegram-only
sudo bash install.sh
```

По умолчанию проект будет развернут в: `/opt/mikrotik-2fa-telegram-only`

## Конфигурация

См. `env.example`.

Минимум для запуска:
- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USERNAME` (без `@`) — первый админ. Бот автоматически “выучит” и сохранит его numeric `user_id` после первого `/start`.

Управление админами через бота:
- `/add_admin <telegram_id|@username>`
- `/remove_admin <telegram_id|@username>`
- `/list_admins`

Дополнительно, админ может менять часть параметров **в рантайме** через Telegram команду `/router_settings`:
- параметры подключения RouterOS API (host/port/ssl/user/pass/timeout)
- поведение VPN/2FA: длительность сессии, таймаут подтверждения, повторные запросы подтверждения, grace period на отключение

## Важные ограничения (по вашему требованию)

- Детект подключений делается **строго через User Manager sessions** (`/user-manager session`) — без PPP fallback.
- Включение/выключение пользователя делается **строго через User Manager user** (`/user-manager user`) — если пользователя нет в User Manager, бот вернёт ошибку.
- Админские команды разрешены по одному из способов:
  - `ADMIN_CHAT_ID` (если задан)
  - `ADMIN_TELEGRAM_IDS` (рекомендуется)
  - `ADMIN_USERNAMES` (fallback)

Чтобы узнать свои значения, используйте команду бота: `/whoami`.

## Лицензия

Свободное использование: [MIT License](LICENSE).

## Поддержать автора

Если проект вам полезен — буду благодарен за поддержку: `https://www.donationalerts.com/r/netcore_24`

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
