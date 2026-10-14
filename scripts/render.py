#!/usr/bin/env python3
"""Рендер всех конфигов Matrix-стека из templates/ + значений .env.

Запускается контейнером `config-init` (образ python:3.12-alpine, только stdlib).
Все переменные берутся из окружения — compose передаёт их через env_file: .env.

Что делает:
  /data/synapse/homeserver.yaml          ← templates/homeserver.yaml.tmpl
  /data/synapse/log.yaml                 ← templates/log.yaml
  /data/mas/config.yaml                  ← templates/mas-config.yaml.tmpl
                                            + секция email (если EMAIL_ENABLED=true)
                                            + блок secrets: из mas-keys (/data/mas/generated.yaml)
  /data/livekit/config.yaml              ← templates/livekit.yaml.tmpl
  /data/nginx/default.conf               ← templates/nginx-site.conf.tmpl
  /data/www/.well-known/matrix/server    ← templates/well-known-server.json.tmpl
  /data/www/.well-known/matrix/client    ← собирается кодом (JSON, с учётом звонков)
  /data/www/index.html                   ← заглушка-указатель

Идемпотентно: можно перезапускать сколько угодно.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys

TEMPLATES = pathlib.Path("/templates")
DATA = pathlib.Path("/data")
CONFIG = DATA / "config"          # не используется, оставлено для совместимости

ENV = os.environ
problems: list[str] = []


def env(name: str, default: str = "") -> str:
    return (ENV.get(name) or default).strip()


def flag(name: str, default: bool = False) -> bool:
    raw = env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "да")


def require(name: str) -> str:
    value = env(name)
    if not value or value.startswith("CHANGEME"):
        problems.append(f"{name} не заполнен (запустите ./scripts/generate-env.sh и проверьте .env)")
    return value


def subst(text: str) -> str:
    """Подстановка ${VAR}. Незаполненные переменные → пустая строка."""
    def repl(m: re.Match[str]) -> str:
        return env(m.group(1))
    return re.sub(r"\$\{([A-Z0-9_]+)\}", repl, text)


def render(template_name: str, target: pathlib.Path, mode: int = 0o644) -> str:
    src = TEMPLATES / template_name
    if not src.exists():
        problems.append(f"нет шаблона {src}")
        return ""
    text = subst(src.read_text(encoding="utf-8"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    target.chmod(mode)
    print(f"  ✔ {target}")
    return text


def write_text(target: pathlib.Path, text: str, mode: int = 0o644) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    target.chmod(mode)
    print(f"  ✔ {target}")


# ------------------------------------------------------------------ значения
SERVER_NAME = require("SERVER_NAME")
PUBLIC_BASE_URL = require("PUBLIC_BASE_URL").rstrip("/")
ENABLE_CALLS = flag("ENABLE_CALLS", False)
EMAIL_ENABLED = flag("EMAIL_ENABLED", False)
TURN_ENABLED = flag("TURN_ENABLED", False)
NODE_IP = env("NODE_IP")
RTC_RANGE_START = env("RTC_RANGE_START", "7882")
RTC_RANGE_END = env("RTC_RANGE_END", "7892")

if PUBLIC_BASE_URL and "://" not in PUBLIC_BASE_URL:
    problems.append("PUBLIC_BASE_URL должен быть со схемой, например https://example.com")

print("== Matrix config render ==")
print(f"   домен: {SERVER_NAME}, база: {PUBLIC_BASE_URL}, звонки: {ENABLE_CALLS}, почта: {EMAIL_ENABLED}")

# ------------------------------------------------------------------ каталоги
for d in (DATA / "synapse/media", DATA / "synapse/logs", DATA / "mas", DATA / "livekit",
          DATA / "nginx", DATA / "www/.well-known/matrix"):
    d.mkdir(parents=True, exist_ok=True)


def chown_tree(path: pathlib.Path, uid: int, gid: int) -> int:
    """Рекурсивно меняет владельца. Возвращает число изменённых объектов."""
    changed = 0
    for p in [path, *path.rglob("*")]:
        try:
            os.chown(p, uid, gid)
            changed += 1
        except OSError as exc:
            print(f"  ! не смог сменить владельца {p}: {exc}", file=sys.stderr)
    return changed

# ------------------------------------------------------------------ Synapse
hs = render("homeserver.yaml.tmpl", DATA / "synapse/homeserver.yaml")
render("log.yaml", DATA / "synapse/log.yaml")

if ENABLE_CALLS:
    hs = hs.rstrip("\n") + (
        "\n\n# ------------------------------------------------------- звонки (LiveKit)\n"
        "matrix_rtc:\n"
        "  transports:\n"
        "    - type: livekit\n"
        f"      livekit_service_url: {PUBLIC_BASE_URL}/livekit/jwt\n"
    )
    write_text(DATA / "synapse/homeserver.yaml", hs)
    print("  ✔ добавил блок matrix_rtc (звонки)")
else:
    print("  · звонки выключены (ENABLE_CALLS=false) — блок matrix_rtc не добавлен")

# ------------------------------------------------------------------ MAS
mas_conf = render("mas-config.yaml.tmpl", DATA / "mas/config.yaml")

if EMAIL_ENABLED:
    from_line = env("EMAIL_FROM") or f'"Matrix Authentication" <{env("SMTP_USERNAME")}>'
    email_block = (
        "\n"
        "# --- почта (писалки MAS: подтверждение адреса, сброс пароля) -----------\n"
        "# ВАЖНО: ключи лежат ПЛОСКО в секции email.\n"
        "# Вложенная форма (email: -> smtp: -> username:) молча игнорируется,\n"
        "# и SMTP-сервер отвечает «send AUTH command first».\n"
        "email:\n"
        f"  transport: smtp\n"
        f"  mode: {env('SMTP_MODE', 'tls')}\n"
        f"  hostname: {env('SMTP_HOST')}\n"
        f"  port: {env('SMTP_PORT', '465')}\n"
        f"  username: {env('SMTP_USERNAME')}\n"
        f"  password: '{env('SMTP_PASSWORD')}'\n"
        f"  from: {from_line}\n"
        f"  reply_to: {from_line}\n"
    )
    mas_conf = mas_conf.rstrip("\n") + "\n" + email_block
    write_text(DATA / "mas/config.yaml", mas_conf)
    print("  ✔ добавил секцию email")
else:
    print("  · EMAIL_ENABLED=false — секции email в конфиге MAS нет (письма не отправляются)")

# --- блок secrets: берём из того, что сгенерировал mas-cli (сервис mas-keys)
# mas-keys пишет в generated.new.yaml. Фиксируем ключи один раз: при последующих
# запусках свежая генерация отбрасывается, иначе смена ключей разлогинивает всех.
gen_new = DATA / "mas/generated.new.yaml"
generated = DATA / "mas/generated.yaml"
if gen_new.exists():
    if not generated.exists():
        gen_new.replace(generated)
        print("  ✔ ключи MAS зафиксированы в /data/mas/generated.yaml")
    else:
        gen_new.unlink()
        print("  · /data/mas/generated.yaml уже есть — новая генерация отброшена")

if not generated.exists() or generated.stat().st_size == 0:
    print("!! НЕТ /data/mas/generated.yaml — ключи MAS не сгенерированы.", file=sys.stderr)
    problems.append("не сгенерированы ключи MAS (сервис mas-keys не отработал)")
else:
    text = generated.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("secrets:"):
            start = i
            break
    if start is None:
        problems.append("в сгенерированном конфиге MAS нет секции secrets:")
    else:
        block = [lines[start]]
        for line in lines[start + 1:]:
            if line and not line[0].isspace():
                break                       # начался следующий ключ верхнего уровня
            block.append(line)
        while block and not block[-1].strip():
            block.pop()
        mas_conf = mas_conf.rstrip("\n") + "\n\n" + "\n".join(block) + "\n"
        write_text(DATA / "mas/config.yaml", mas_conf)
        print(f"  ✔ вписал блок secrets: ({len(block)} строк) из generated.yaml")

# --- проверка: секрет Synapse и MAS обязан совпадать (иначе логин не работает)
ms = env("MAS_MATRIX_SECRET")
if ms:
    if f'secret: "{ms}"' not in hs:
        problems.append("MAS_MATRIX_SECRET не попал в homeserver.yaml")
    if f'secret: "{ms}"' not in mas_conf:
        problems.append("MAS_MATRIX_SECRET не попал в конфиг MAS")

# ------------------------------------------------------------------ LiveKit
lk = render("livekit.yaml.tmpl", DATA / "livekit/config.yaml")
node_lines = f"  use_external_ip: false\n  node_ip: {NODE_IP}" if NODE_IP else "  use_external_ip: true"
lk = lk.replace("  #__NODE_IP_LINES__", node_lines)

# Ловушка: use_external_ip + диапазон из одного порта = паника LiveKit (rand.Intn(0)).
try:
    rs, re_ = int(RTC_RANGE_START), int(RTC_RANGE_END)
    if rs > re_:
        problems.append(f"RTC_RANGE_START ({rs}) больше RTC_RANGE_END ({re_})")
    elif rs == re_ and not NODE_IP:
        problems.append(
            f"RTC_RANGE_START == RTC_RANGE_END == {rs} при пустом NODE_IP: LiveKit "
            "упадёт в панику (rand.Intn(0)). Либо задайте диапазон шире "
            "(например 7882 и 7892), либо укажите NODE_IP.")
except ValueError:
    problems.append("RTC_RANGE_START/RTC_RANGE_END должны быть числами")
write_text(DATA / "livekit/config.yaml", lk)
print(f"  ✔ LiveKit: {'node_ip=' + NODE_IP if NODE_IP else 'use_external_ip=true (автоопределение)'}")

# ------------------------------------------------------------------ nginx
render("nginx-site.conf.tmpl", DATA / "nginx/default.conf")

# ------------------------------------------------------------------ well-known
render("well-known-server.json.tmpl", DATA / "www/.well-known/matrix/server")

client: dict = {
    "m.homeserver": {"base_url": PUBLIC_BASE_URL},
    "org.matrix.msc2965.authentication": {
        "issuer": f"{PUBLIC_BASE_URL}/",
        "account": f"{PUBLIC_BASE_URL}/account/",
    },
}
if ENABLE_CALLS:
    client["org.matrix.msc4143.rtc_foci"] = [
        {"type": "livekit", "livekit_service_url": f"{PUBLIC_BASE_URL}/livekit/jwt"}
    ]
    if TURN_ENABLED and env("TURN_CREDENTIAL"):
        # ICE/TURN: адреса, которые клиенты пробуют по очереди.
        client["org.matrix.msc4143.ice_servers"] = [{
            "urls": [
                f"turn:{SERVER_NAME}:3478?transport=udp",
                f"turn:{SERVER_NAME}:3478?transport=tcp",
                f"turn:{SERVER_NAME}:5349?transport=tcp",
            ],
            "username": env("TURN_USERNAME", "turn"),
            "credential": env("TURN_CREDENTIAL"),
        }]
write_text(DATA / "www/.well-known/matrix/client",
           json.dumps(client, indent=2, ensure_ascii=False) + "\n")
print("  ✔ /.well-known/matrix/client")

# ------------------------------------------------------------------ заглушка
index = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>{SERVER_NAME}</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:44rem;margin:4rem auto;padding:0 1rem;line-height:1.6}}
 code{{background:#f2f2f2;padding:.15em .35em;border-radius:.25em}}
</style></head><body>
<h1>{SERVER_NAME}</h1>
<p>Сервер Matrix работает. Этот адрес — точка входа API, а не веб-приложение.</p>
<ul>
  <li>Подключиться клиентом: <code>{PUBLIC_BASE_URL}</code> (Element Desktop, Element X, Element Web)</li>
  <li>Состояние: <a href="/_matrix/federation/v1/version">/_matrix/federation/v1/version</a></li>
  <li>Проверка федерации: <a href="https://federationtester.matrix.org/#{SERVER_NAME}">federationtester.matrix.org</a></li>
</ul>
</body></html>
"""
write_text(DATA / "www/index.html", index)

# ------------------------------------------------------------------ роуты nginx
# conf.d/default.conf не должен быть исполняемым, но должен читаться nginx (uid 101)
(DATA / "nginx/default.conf").chmod(0o644)

# ------------------------------------------------------------------ владелец
# Synapse в официальном образе ВСЕГДА работает под uid 991 (в start.py:
# «if we are running as root, use user 991»), а каталог на bind-mount создаётся
# root'ом — без выравнивания владельца Synapse не может записать ключ подписи,
# медиа и лог (падает с PermissionError и уходит в рестарт-цикл).
# На Docker Desktop (macOS/Windows) владелец не важен — там это no-op.
S_UID = int(env("SYNAPSE_UID", "991"))
S_GID = int(env("SYNAPSE_GID", "991"))
if os.geteuid() == 0:
    n = chown_tree(DATA / "synapse", S_UID, S_GID)
    print(f"  ✔ владелец /data/synapse → {S_UID}:{S_GID} ({n} объектов)")
else:
    print("  · не root — владельца не меняю (норма для Docker Desktop)")

# ------------------------------------------------------------------ итог
print("\n== Результат ==")
if problems:
    print("ПРОБЛЕМЫ:")
    for p in problems:
        print("  ✖", p)
    sys.exit(1)
print("  все конфиги готовы")
