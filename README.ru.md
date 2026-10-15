![Собственный сервер Matrix в одном docker compose](docs/img/banner.svg)

# Matrix-стек: Synapse + MAS + PostgreSQL + nginx

Переносимая сборка рабочего сервера Matrix. Разворачивается одной командой
`docker compose up -d`, все настройки — в одном файле `.env`.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Docker Compose](https://img.shields.io/badge/docker-compose-2496ED?logo=docker&logoColor=white)
![Synapse](https://img.shields.io/badge/Synapse-1.162.0-58a6ff)
![MAS](https://img.shields.io/badge/MAS-1.26.0-a371f7)

![Звонки: голос и видео](https://img.shields.io/badge/calls-voice%20%26%20video-39c5cf)
![QR-вход](https://img.shields.io/badge/QR%20login-MSC4108-3fb950)
![Element X](https://img.shields.io/badge/Element%20X-iOS%20%7C%20Android-a371f7)
![Федерация](https://img.shields.io/badge/federation-yes-58a6ff)

**Русский** · [English](README.md)

Состав:

| Компонент | Образ | Роль |
|---|---|---|
| Synapse `1.162.0` | `matrixdotorg/synapse` | сам homeserver |
| MAS `1.26.0` | `ghcr.io/element-hq/matrix-authentication-service` | вход/регистрация (OAuth2/OIDC), пароли, устройства |
| PostgreSQL `16` | `postgres:16-alpine` | БД `synapse` + `mas` |
| nginx `1.27` | `nginx:1.27-alpine` | единая точка входа, well-known, маршрутизация |
| LiveKit `1.13.9` + lk-jwt `0.7.0` | профиль `calls` | звонки (Element Call / Element X) |

Аутентификацией занимается **только MAS** (`matrix_authentication_service`):
регистрация и вход в Synapse идут через него, у Synapse своя регистрация выключена.

### Голосовые и видеозвонки, QR-вход, Element X

- **Голосовые и видеозвонки** — индивидуальные и групповые, через **LiveKit** (профиль `calls`),
  с TURN для клиентов за сложным NAT. При включённых звонках сгенерированные конфиги содержат
  блок `matrix_rtc` в Synapse и `org.matrix.msc4143.rtc_foci` + `org.matrix.msc4143.ice_servers`
  в `/.well-known/matrix/client` — именно это читают Element Call, Element Web/Desktop и Element X,
  чтобы начать звонок.
- **Element X (iOS / Android)** — поддерживается полностью: вход по OAuth2/OIDC через MAS
  (discovery на `/.well-known/openid-configuration`, публичный клиент без секрета), звонки,
  управление устройствами и сессиями, QR-вход.
- **QR-вход** — привязка нового устройства сканированием QR-кода с уже открытой сессии:
  `msc4108_enabled: true` и оба локейшена `rendezvous` без буферизации и без gzip
  (порядок локейшенов важен — см. `templates/nginx-site.conf.tmpl`).

QR-вход работает между Element X, Element Web и Element Desktop: одна сессия показывает код,
новое устройство его сканирует — вводить пароль или токен на новом устройстве не нужно.

![Схема стека](docs/img/architecture.svg)

Что видно на схеме: клиенты и чужие серверы → **nginx :80** → либо
**Synapse :8008** (`/_matrix/client`, `/_matrix/federation`, `/_synapse/admin`),
либо **MAS :8082** (`/login`, `/register`, `/oauth2`, `/account`); оба работают с
**PostgreSQL**. `/.well-known/matrix/*` nginx отдаёт сам.

---

## 1. Требования

- Linux с Docker Engine 24+ и Docker Compose v2 (`docker compose version`).
- Домен, A-запись которого указывает на этот сервер (в примерах — `example.com`).
- Открытые порты: `80` (или `443` через ваш TLS-прокси), `8448` — не обязателен,
  федерация работает через `.well-known/matrix/server` на 443.
- Минимум: 2 ГБ RAM, 10 ГБ диска. Для звонков — больше и публичный IP.
- ~2.5 ГБ трафика на первичную загрузку образов.

> **Windows / macOS.** Сам стек поднимается штатно (`docker compose up -d` из
> PowerShell тоже работает), но `scripts/generate-env.sh` — это shell-скрипт:
> запускайте его в WSL или Git Bash, либо просто скопируйте `.env.example` в
> `.env` и заполните `CHANGEME_*` любыми случайными строками
> (`openssl rand -hex 32`). Проверки владельцев файлов на Docker Desktop не
> выполняются — это нормально, там они не нужны.

## 2. Быстрый старт

```bash
cd matrix-stack

# 1) генерируем секреты (создаёт .env и заполняет все пароли/ключи)
./scripts/generate-env.sh

# 2) правим в .env ДВА обязательных значения
nano .env
#    SERVER_NAME=example.com            <- ваш домен
#    PUBLIC_BASE_URL=https://example.com <- адрес со схемой, без слэша на конце

# 3) поднимаем
docker compose up -d

# 4) смотрим, что всё встало
docker compose ps
docker compose logs -f config-init   # рендер конфигов, должен закончиться «все конфиги готовы»
```

Через 30–60 секунд проверьте:

```bash
curl -s http://127.0.0.1:${HTTP_PORT:-80}/_matrix/federation/v1/version   # версия Synapse
curl -s http://127.0.0.1:${HTTP_PORT:-80}/.well-known/matrix/client      # настройки для клиентов
```

Или одной строкой (порт берётся из `.env`):

```bash
set -a; . ./.env; set +a; curl -s "http://127.0.0.1:${HTTP_PORT}/_matrix/client/versions" | head -c 300
```

![Порядок запуска](docs/img/startup.svg)

Порядок запуска задан в compose: `postgres (healthy) → mas-keys → config-init → synapse/mas → nginx`.
Сервисы `mas-keys` и `config-init` — одноразовые «сборщики конфигов», в `docker compose ps`
они висят как `Exited (0)` — это нормально.

## 3. Что где лежит

```
.
├── docker-compose.yml
├── .env.example          # шаблон настроек (копируется в .env)
├── initdb/01-databases.sh# создание ролей и БД при первом старте PostgreSQL
├── scripts/
│   ├── generate-env.sh   # .env + случайные секреты (запускать на хосте)
│   └── render.py         # рендер конфигов из шаблонов (внутри контейнера)
├── templates/            # ИСТОЧНИК ПРАВДЫ для конфигов
│   ├── homeserver.yaml.tmpl
│   ├── mas-config.yaml.tmpl
│   ├── livekit.yaml.tmpl
│   ├── nginx-site.conf.tmpl
│   ├── log.yaml
│   └── well-known-server.json.tmpl
└── data/                 # состояние (создаётся при запуске, НЕ в git)
    ├── postgres/         # БД
    ├── synapse/          # homeserver.yaml (выход render), media/, logs/, ключ подписи
    ├── mas/              # config.yaml + generated.yaml (ключи MAS)
    ├── livekit/          # config.yaml
    ├── nginx/default.conf
    └── www/              # .well-known, index.html, element-web/, admin/
```

**Правки настроек делаются только в `templates/` и `.env`,** потом:

```bash
docker compose up -d config-init --force-recreate   # перегенерировать конфиги
docker compose restart synapse mas                   # применить
```

Файлы внутри `data/` перезаписываются — не редактируйте их руками.

## 4. DNS и TLS

DNS: одна A-запись `example.com → IP сервера`. Остальное — через well-known:

```bash
curl -s https://example.com/.well-known/matrix/server   # {"m.server": "example.com:443"}
```

TLS в этот бандл не входит намеренно: вариантов слишком много.

- **Есть внешний прокси** (Nginx Proxy Manager, Caddy, Traefik, облако) — направьте
  домен на `http://IP:${HTTP_PORT}` и включите WebSocket + передачу заголовков
  `X-Forwarded-For` / `X-Forwarded-Proto: https`. Больше ничего не нужно.
- **Прокси нет** — самый быстрый путь: поставить перед compose Caddy
  (`caddy reverse-proxy --from example.com --to 127.0.0.1:80`) либо добавить
  отдельный сервис с certbot и смонтировать сертификаты в nginx-контейнер.

Если TLS терминируется не на nginx из этого compose, обязательно выставите
`PUBLIC_BASE_URL=https://...` — MAS подписывает токены этим адресом, при рассинхроне
клиенты получат ошибку `invalid issuer`.

## 5. Первый пользователь, админ, регистрация

Регистрация идёт через MAS. По умолчанию в `.env` стоит
`REGISTRATION_TOKEN_REQUIRED=true` — регистрация только по одноразовому токену.

Все команды `mas-cli` работают без флага `-c`: путь к конфигу задан переменной
`MAS_CONFIG=/data/config.yaml` в compose.

```bash
# одноразовый токен регистрации (действует 1 час) — выдавать пользователю
docker compose exec mas mas-cli manage issue-user-registration-token

# создать пользователя сразу (без похода в веб-форму)
docker compose exec mas mas-cli manage register-user alice -y -p 'Пароль-На-Выбор'

# список пользователей, которым разрешено ЗАПРАШИВАТЬ админ-права
docker compose exec mas mas-cli manage list-admin-users

# выдать админ-права / снять
docker compose exec mas mas-cli manage promote-admin alice
docker compose exec mas mas-cli manage demote-admin alice

# сменить пароль, заблокировать, убить сессии
docker compose exec mas mas-cli manage set-password alice
docker compose exec mas mas-cli manage lock-user alice
docker compose exec mas mas-cli manage kill-sessions alice
```

Пользователь входит в клиенте (Element Desktop / Element X) по адресу
`PUBLIC_BASE_URL`, вводя логин, пароль и токен регистрации.

Страницы входа и аккаунта отдаёт сам MAS — отдельный веб-клиент для них не нужен:

| Страница входа (`/login`) | Страница аккаунта (`/account/sessions`) |
|---|---|
| ![Вход](docs/img/login.png) | ![Аккаунт](docs/img/account.png) |

*(снимки сделаны на тестовом прогоне, описанном в §12, — домен там условный)*

### Как устроены админ-права (важно не перепутать)

- `policy.data.admin_users` (в шаблоне — `ADMIN_USER` из `.env`) — это список тех,
  кто может **запрашивать** админ-права. Сам факт наличия в списке прав не даёт:
  `list-admin-users` так и пишет — «can request admin privileges».
- Реальные права выдаёт `promote-admin`.
- Права администратора в этой схеме — **OAuth-скоуп**: Synapse считает вас
  серверным админом, только если у токена есть скоуп `urn:synapse:admin:*`
  (проверено по коду Synapse `synapse/api/auth/mas.py`: `is_server_admin` →
  `"urn:synapse:admin:*" in requester.scope`). Скоуп запрашивает клиент в
  OAuth-потоке, и он «зашит» в выданный токен.
- Поэтому **обычный вход по логину/паролю не даёт прав на `/_synapse/admin/`** —
  даже сразу после `promote-admin` и повторного входа мы получали
  `403 You are not a server admin` (токен выдан без админ-скоупа).
  Администрируйте через MAS: `mas-cli`, панель (Ketesa) или MAS admin API.
- `REGISTRATION_TOKEN_REQUIRED=false` — открытая регистрация (для закрытого теста).

### Про поиск пользователей

Приглашать и искать чужих пользователей можно только по полному MXID
(`@user:другой.домен`). Поиск по отображаемому имени чужака не работает by design:
клиент ищет только в локальном каталоге, а каталог содержит только пользователей
этого сервера.

## 6. Веб-клиент и панель (необязательно)

nginx уже настроен обслуживать:

- `https://example.com/element-web/` → положите сборку Element Web в `data/www/element-web/`
  и в её `config.json` укажите `{"default_server_config":{"m.homeserver":{"base_url":"https://example.com"}},
  "oidc_client_id":"<OIDC_CLIENT_ID из .env>"}`.
- `https://example.com/admin/` → статичная сборка панели (например Ketesa) в `data/www/admin/`.

Ничего не положите — просто будут 404, остальной стек это не затрагивает.

## 7. Звонки (профиль `calls`)

```bash
# в .env: ENABLE_CALLS=true  (плюс LIVEKIT_KEY/SECRET уже сгенерированы)
docker compose up -d config-init --force-recreate
docker compose --profile calls up -d
```

Открыть наружу для медиа:

| Порт | Протокол | Назначение |
|---|---|---|
| 7881 | TCP | ICE/медиа поверх TCP |
| `${RTC_RANGE_START}-${RTC_RANGE_END}` (по умолчанию 7882–7892) | UDP | медиа |
| `${TURN_UDP_PORT}` (3478) | UDP | TURN (если `TURN_ENABLED=true`) |
| `${TURN_TLS_PORT}` (5349) | TCP | TURN/TLS (если `TURN_ENABLED=true`) |
| 443 | TCP | `/livekit/sfu` (WebSocket) через внешний прокси |

Проверка: `curl -s https://example.com/livekit/jwt/healthz` → `OK`.

Осторожно:

- `LIVEKIT_JWT_BIND` **обязан** быть `0.0.0.0:8084`. Со `localhost` сервис биндится
  на IPv6-loopback и nginx его не видит (в этом compose уже прописано).
- Если сервер за NAT — заполните `NODE_IP` вашим внешним IP, иначе медиа поедет на
  внутренний адрес и звонки будут «подключаться без звука/видео».
- Диапазон UDP-портов при пустом `NODE_IP` **обязан** содержать больше одного
  порта: LiveKit выбирает случайный порт из диапазона, и на диапазоне из одного
  порта падает в панику `invalid argument to Intn` ещё до старта. Один порт можно
  указать только вместе с `NODE_IP`. `config-init` проверяет это и останавливается
  с понятным сообщением.
- lk-jwt оставлен на `0.7.0`: в `0.8.0` изменён формат `/get_token` и старые клиенты
  ломаются. Обновляя — проверьте звонок в Element X.
- TURN требует валидного сертификата на домен: либо внешний прокси с TLS на 5349,
  либо `TURN_EXTERNAL_TLS=false` (клиенты будут жаловаться на самоподписанный).

## 8. Федерация

```bash
curl -s "https://federationtester.matrix.org/api/report?server_name=example.com" | \
  python3 -m json.tool | grep -E '"FederationOK"|"ServerName"|"error"'
```

Ожидаемое — `"FederationOK": true`. Если `false` — почти всегда внешний прокси:
не отдаёт `/.well-known/matrix/server`, не передаёт `X-Forwarded-Proto`, либо
блокирует `POST /_matrix/federation/v1/send/...`.

Проверка вручную с другой машины:

```bash
curl -s https://example.com/_matrix/key/v2/server | head -c 200
curl -s -o /dev/null -w '%{http_code}\n' https://example.com/_matrix/federation/v1/version
```

## 9. Обслуживание

```bash
# логи
docker compose logs -f synapse          # консоль
tail -f data/synapse/logs/homeserver.log # файл (ротация 50 МБ × 5) — так надёжнее

# состояние
docker compose ps
docker compose exec synapse curl -s localhost:8008/_matrix/client/versions

# бэкап (минимум — БД + ключ подписи; без ключа федерация «сломается» молча)
docker compose exec -T postgres pg_dump -U matrix synapse | gzip > synapse-$(date +%F).sql.gz
docker compose exec -T postgres pg_dump -U matrix mas     | gzip > mas-$(date +%F).sql.gz
sudo tar czf matrix-data-$(date +%F).tgz data/synapse/homeserver.signing.key \
     data/config data/mas/generated.yaml

# обновление
sed -i 's/^SYNAPSE_IMAGE=.*/SYNAPSE_IMAGE=matrixdotorg\/synapse:v1.163.0/' .env
docker compose pull && docker compose up -d

# полная остановка (данные сохраняются)
docker compose down
# стереть ВСЁ, включая БД:  docker compose down && sudo rm -rf data
```

Версии компонентов закреплены в `.env` (`SYNAPSE_IMAGE`, `MAS_IMAGE`, …) — чтобы
обновление было осознанным действием, а не сюрпризом.

## 10. Частые проблемы

| Симптом | Причина и что делать |
|---|---|
| `Invalid MAC` / 500 в логах Synapse | `MAS_MATRIX_SECRET` не совпал в `homeserver.yaml` и конфиге MAS. Смотрите вывод `config-init`: он проверяет это и падает. |
| Заходят только локальные, федерация `FederationOK: false` | Внешний прокси: нет `/.well-known/matrix/server` или не передаётся `X-Forwarded-Proto`. |
| `{"errcode":"M_UNRECOGNIZED"}` на login | Запрос уходит мимо MAS. Проверьте в nginx локейшены `^/_matrix/client/(v1|v3|unstable)/(login\|logout\|refresh)`. |
| CSS/картинки со страниц входа не грузятся | nginx не проксирует `/assets/` и `/oauth2/` на MAS. |
| Сброс пароля/письма не приходят | `EMAIL_ENABLED=false` — письма не отправляются вообще. Включите и проверьте, что ключи SMTP лежат **плоско** в секции `email:` (вложенная форма молча игнорируется, SMTP ответит `send AUTH command first`). |
| QR-вход («Связать устройство») не работает | Нужен `msc4108_enabled: true` (есть) и локейшены `rendezvous` без буферизации (есть). |
| Порты заняты, `docker compose up` падает | Смените `HTTP_PORT` (и `RTC_RANGE_START/END`, `TURN_*_PORT`) в `.env`. |
| LiveKit в рестарт-цикле, в логах `panic: invalid argument to Intn` | `RTC_RANGE_START == RTC_RANGE_END` при пустом `NODE_IP`. Сделайте диапазон шире или задайте `NODE_IP`. |
| nginx не стартует: `host not found in upstream` | Апстримы звонков в конфиге отрендерены не из шаблона (шаблон использует resolver). Перегенерируйте: `docker compose up -d config-init --force-recreate`. |
| Synapse в рестарт-цикле, `PermissionError: /data/homeserver.signing.key` | Каталог `data/synapse` принадлежит root, а Synapse работает под uid 991. `config-init` выравнивает владельца; если запускали compose вручную без него — `sudo chown -R 991:991 data/synapse`. |
| `mas-cli` в контейнере: `could not connect to the database` | Забыли переменную `MAS_CONFIG` (в этом compose она уже задана) — либо передайте `-c /data/config.yaml`. |
| `403 You are not a server admin` в `/_synapse/admin/` | У токена нет скоупа `urn:synapse:admin:*` — см. §5. Админьте через MAS. |
| Конфиг не подхватился после правки шаблона | Забыли `docker compose up -d config-init --force-recreate` + `restart synapse mas`. |
| Звонок соединяется, но без медиа | NAT: не заполнен `NODE_IP` либо закрыт UDP-порт `RTC_RANGE`. |

## 11. Чего в бандле нет

- **TLS-сертификатов** — принесите свой (см. §4).
- **Веб-клиента и админ-панели** — положите статичные сборки в `data/www/` (§6).
- **TURN как отдельной службы** — TURN встроен в LiveKit (`TURN_ENABLED=true`).
- **Мостов** (IRC/Slack/Telegram) и ботов — ставится отдельно поверх этого стека.
- **Автобэкапов** — команды в §9, поставьте их в cron сами.

## 12. Что проверено вживую

Бандл не просто написан — он поднят и прогнан целиком на чистой машине
(Ubuntu, Docker 29.9 / Compose v5.6, все семь контейнеров). Результаты:

| Проверка | Результат |
|---|---|
| `docker compose up -d` с нуля, все контейнеры | `postgres` healthy, `synapse` healthy, `mas` up, `nginx` up, `livekit` up, `lk-jwt` healthy |
| `GET /_matrix/client/versions` через nginx | 200, список версий |
| `GET /_matrix/federation/v1/version` | `{"server":{"name":"Synapse","version":"1.162.0"}}` |
| `GET /.well-known/matrix/server` и `/client` | корректный JSON, `m.server`, MSC2965-блок |
| `GET /_matrix/client/v3/login` | 200, потоки `m.login.password` + `m.login.sso` — значит запрос обслужил MAS |
| MAS health (`http://mas:8081/health`) | `ok` |
| Регистрация пользователя (`mas-cli manage register-user`) | `User registered user.id=01M4XZ4PZ1…` |
| Вход `POST /_matrix/client/v3/login` | 200, `user_id=@admin:…`, `device_id`, токен `mct_…` |
| `GET /_matrix/client/v3/account/whoami` | 200, корректный `user_id` |
| `POST /_matrix/client/v3/createRoom` | 200, `room_id` |
| `GET /_matrix/client/v3/devices` | 200 |
| Пользователь провижинится в БД Synapse | `@admin:matrix.test.local` появился в таблице `users` |
| `lk-jwt` `GET /livekit/jwt/healthz` через nginx | 200 |
| LiveKit через nginx (`/livekit/sfu/`) | 200 |
| Стек **без** профиля `calls` | nginx стартует, ядро API 200, `/livekit/*` → 502 (не падение) |
| Веб-интерфейс через nginx (`/login`, `/account/sessions`) | обе страницы открываются, вход созданным пользователем проходит |
| Звонки: блок `matrix_rtc` в отрендеренном `homeserver.yaml` | есть, `livekit_service_url` = `${PUBLIC_BASE_URL}/livekit/jwt` |
| Звонки: `org.matrix.msc4143.rtc_foci` в `/.well-known/matrix/client` | есть, ведёт на `/livekit/jwt`; `ice_servers` (TURN) добавляются при `TURN_ENABLED=true` |
| QR-вход: `msc4108_enabled: true` и оба локейшена `rendezvous` | включено; проксируются с `proxy_buffering off` и `gzip off` |

Чего в прогоне **не было**: сам звонок и сканирование QR-кода телефоном — для этого нужны
реальные клиенты на реальных устройствах. Всё, от чего они зависят (foci, ICE-серверы,
rendezvous-эндпоинты, health-эндпоинты), генерируется и отдаётся так, как указано выше.

Побочный результат прогона — четыре грабли, которые ломают такой стек «из коробки»
(все исправлены и описаны выше): отсутствие шелла и uid 65532 в образе MAS;
принудительный uid 991 у Synapse против bind-mount от root; паника LiveKit на
диапазоне из одного UDP-порта; падение nginx из-за неразрешимого апстрима
опционального сервиса.

---

### Технические решения, о которых стоит знать

- **Ключи MAS не генерируются вручную.** `render.py` вызывает штатный
  `mas-cli config generate` и переносит из результата только блок `secrets:`
  (ключи подписи и ключ шифрования). Формат этих ключей специфичен, самодельный
  ломает MAS.
- **Админ-права — в MAS**, не в Synapse: `policy.data.admin_users` (плюс
  `ADMIN_USER` из `.env`). Это следствие MSC3861 — Synapse не хранит пароли.
- **`exclude_remote_users: true`** в `user_directory` — чужие пользователи не мусорят
  поиск; приглашение по полному MXID при этом работает нормально.
- **Логи Synapse пишутся на диск** (`data/synapse/logs/`), а не только в консоль:
  иначе после перезапуска контейнера разбираться в инциденте нечем.
- **Медиа-ретеншн** включён (своё 30 дней, чужое 7) — иначе диск забивается
  «мусором» федерации.
- **`trusted_proxies: 172.16.0.0/12`** в MAS — адреса docker-сети, откуда приходит
  nginx. Если меняете подсети compose, поправьте и это.

---

🇬🇧 **Read in English:** [README.md](README.md) — the same document in English.
