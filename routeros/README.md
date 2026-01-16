## Запуск на MikroTik (RouterOS Container, arm64)

Эта инструкция для устройств MikroTik с **RouterOS v7 + Container** и архитектурой **arm64** (aarch64).

### Что важно знать

- MikroTik **не умеет собирать Docker-образы**. Образ нужно собрать на ПК/сервере и **запушить в registry** (Docker Hub / GHCR / свой).
- На MikroTik мы просто **пуллим образ** и передаём **env-переменные** (на RouterOS это делается через `envlist`, а не через `.env` файл).
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

## 2) Что нужно задать (env) и куда примонтировать БД

### 2.1) Обязательные переменные (как в `.env`, только на RouterOS)

Минимум без которого бот не стартует:

- `TELEGRAM_BOT_TOKEN`
- `ADMIN_USERNAME` (без `@`)
- `MIKROTIK_HOST`
- `MIKROTIK_USERNAME`
- `MIKROTIK_PASSWORD`

Рекомендуемое (чтобы SQLite лежал в примонтированной папке):

- `DATABASE_URL=sqlite:////app/data/app.db`

Важно: в `sqlite:////...` **четыре слэша** — это абсолютный путь внутри контейнера.

### 2.2) Папка на диске MikroTik под SQLite

Создайте папку на диске MikroTik, например:

- `/disk1/mikrotik-2fa/data`

Эта папка будет примонтирована в контейнер как:

- host: `/disk1/mikrotik-2fa/data`
- container: `/app/data`

---

## 3) Пример RouterOS команд (копи‑паст с плейсхолдерами)

Замените:

- `<WAN>` — ваш выход в интернет (например `ether1`/`pppoe-out1`)
- `<DISK_PATH>` — путь к папке (например `/disk1/mikrotik-2fa/data`)

### 3.1) Сеть для контейнера (veth + NAT)

```routeros
/interface veth add name=veth-2fa address=172.31.255.2/24 gateway=172.31.255.1
/interface bridge add name=br-containers
/interface bridge port add bridge=br-containers interface=veth-2fa
/ip address add address=172.31.255.1/24 interface=br-containers
/ip firewall nat add chain=srcnat src-address=172.31.255.0/24 out-interface=<WAN> action=masquerade
```

### 3.2) Mount для SQLite

```routeros
/container mounts add name=mt2fa-data src=<DISK_PATH> dst=/app/data
```

### 3.3) Env-переменные (envlist)

```routeros
/container envs add list=mt2fa key=TELEGRAM_BOT_TOKEN value="PASTE_TOKEN"
/container envs add list=mt2fa key=ADMIN_USERNAME value="adminusername"
/container envs add list=mt2fa key=MIKROTIK_HOST value="10.0.243.1"
/container envs add list=mt2fa key=MIKROTIK_USERNAME value="apiuser"
/container envs add list=mt2fa key=MIKROTIK_PASSWORD value="secret"
/container envs add list=mt2fa key=DATABASE_URL value="sqlite:////app/data/app.db"
```

### 3.4) Добавить и запустить контейнер

```routeros
/container add name=mikrotik-2fa image=docker.io/netcore24/mikrotik-2fa-telegram-only:arm64 interface=veth-2fa envlist=mt2fa mounts=mt2fa-data start-on-boot=yes
/container start mikrotik-2fa
```

---

## 4) Проверка

- В Telegram отправьте боту `/start`
- Админом выполните `/test_router` — он покажет диагностику доступа к RouterOS API

