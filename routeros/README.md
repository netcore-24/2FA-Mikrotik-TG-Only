## Запуск на MikroTik (RouterOS Container, arm64)

Эта инструкция для устройств MikroTik с **RouterOS v7 + Container** и архитектурой **arm64** (aarch64).

### Что важно знать

- MikroTik **не умеет собирать Docker-образы**. Образ нужно собрать на ПК/сервере и **запушить в registry** (Docker Hub / GHCR / свой).
- На MikroTik мы просто **пуллим образ** и передаём **env-переменные**.
- База данных по умолчанию — SQLite. Её нужно хранить на диске MikroTik и примонтировать в контейнер.

---

## 1) Сборка и публикация arm64-образа (на вашем ПК/сервере)

Выберите registry и имя образа (пример ниже — Docker Hub):

```bash
export IMAGE="docker.io/<ваш_логин>/mikrotik-2fa-telegram-only:arm64"
docker login

# Собираем и пушим именно arm64:
docker buildx build --platform linux/arm64 -t "$IMAGE" --push .
```

---

## 2) Настройка MikroTik (в общих чертах)

Дальше нужны 3 вещи:

- **Хранилище** (куда положить SQLite БД)
- **Сеть** контейнера
- **Переменные окружения** для бота

### 2.1) Подготовить папку под БД

Создайте папку на диске MikroTik, например:

- `/disk1/mikrotik-2fa/data`

### 2.2) Переменные окружения

Минимум:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USERNAME` (без `@`)
- `MIKROTIK_HOST`
- `MIKROTIK_USERNAME`
- `MIKROTIK_PASSWORD`

Рекомендуемое для БД:

- `DATABASE_URL=sqlite:////app/data/app.db`

### 2.3) Добавить контейнер

Создайте container из образа `IMAGE`, примонтируйте `/app/data` и передайте env.

Я намеренно не расписываю здесь точный CLI RouterOS, потому что он зависит от вашей схемы дисков/bridge/veth.
Логика всегда одна:

- `root-dir` (если нужен)
- `mounts`: host dir → `/app/data`
- `envlist`: список переменных окружения
- `image`: ваш `$IMAGE`
- `start`

---

## 3) Проверка

- В Telegram отправьте боту `/start`
- Админом выполните `/test_router` — он покажет диагностику доступа к RouterOS API

