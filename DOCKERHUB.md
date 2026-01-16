## MikroTik 2FA VPN (Telegram-only)

Telegram-бот для управления доступом к VPN на MikroTik **без веб-интерфейса**.  
Работает **только через RouterOS API** (8728/8729) и **User Manager**.

### Быстрый старт (docker compose)

1) Создайте `.env` (от `env.example`) и заполните минимум:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USERNAME` (без `@`)
- `MIKROTIK_HOST`, `MIKROTIK_USERNAME`, `MIKROTIK_PASSWORD`

2) Запуск:

```bash
mkdir -p data
docker run --rm --env-file .env -v "$PWD/data:/app/data" docker.io/netcore24/mikrotik-2fa-telegram-only:arm64
```

Если вы запускаете не на arm64 — используйте свой multi-arch тег (например `:latest`), либо запускайте через ветку `docker` репозитория.

### MikroTik (RouterOS Containers, arm64)

Образ для MikroTik arm64: `docker.io/netcore24/mikrotik-2fa-telegram-only:arm64`  
Инструкция: смотрите `routeros/README.md` в репозитории.

