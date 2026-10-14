#!/bin/sh
# =============================================================================
#  Создаёт .env из .env.example и заполняет все CHANGEME_* случайными значениями.
#  Запускать на ХОСТЕ (не в контейнере): ./scripts/generate-env.sh
#  Существующий .env не перезаписывается (для перегенерации: ./scripts/generate-env.sh --force)
# =============================================================================
set -eu

cd "$(dirname "$0")/.."

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

if [ -f .env ] && [ "$FORCE" -eq 0 ]; then
    echo "!! .env уже существует — не трогаю (перегенерация: $0 --force)"
    exit 0
fi

# --- генератор случайных значений -------------------------------------------
rnd_hex() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$1"
    elif [ -r /dev/urandom ]; then
        od -An -tx1 -N "$1" /dev/urandom | tr -d ' \n'
    else
        echo "!! нет ни openssl, ни /dev/urandom — заполните секреты руками" >&2
        exit 1
    fi
}

POSTGRES_SUPERUSER_PASSWORD=$(rnd_hex 16)
SYNAPSE_DB_PASSWORD=$(rnd_hex 16)
MAS_DB_PASSWORD=$(rnd_hex 16)
SYNAPSE_MACAROON=$(rnd_hex 32)
SYNAPSE_REG_SHARED=$(rnd_hex 32)
MAS_MATRIX_SECRET=$(rnd_hex 32)
LIVEKIT_KEY="API$(rnd_hex 6)"
LIVEKIT_SECRET=$(rnd_hex 32)
OIDC_CLIENT_ID=$(rnd_hex 13 | tr 'a-f' 'A-F')

cp .env.example .env
chmod 600 .env

# --- подстановка (значения — только hex, sed безопасен) ---------------------
subst() {
    # $1 = ключ, $2 = значение
    if sed --version >/dev/null 2>&1; then
        sed -i "s|^\($1=\).*|\1$2|" .env            # GNU sed
    else
        sed -i '' "s|^\($1=\).*|\1$2|" .env         # BSD/macOS sed
    fi
}

subst POSTGRES_SUPERUSER_PASSWORD "$POSTGRES_SUPERUSER_PASSWORD"
subst SYNAPSE_DB_PASSWORD        "$SYNAPSE_DB_PASSWORD"
subst MAS_DB_PASSWORD            "$MAS_DB_PASSWORD"
subst SYNAPSE_MACAROON_SECRET_KEY "$SYNAPSE_MACAROON"
subst SYNAPSE_REGISTRATION_SHARED_SECRET "$SYNAPSE_REG_SHARED"
subst MAS_MATRIX_SECRET          "$MAS_MATRIX_SECRET"
subst OIDC_CLIENT_ID             "$OIDC_CLIENT_ID"
subst LIVEKIT_KEY                "$LIVEKIT_KEY"
subst LIVEKIT_SECRET             "$LIVEKIT_SECRET"

echo "✔ .env создан, секреты сгенерированы (права 600)."
echo
echo "Теперь ОБЯЗАТЕЛЬНО проверьте в .env:"
echo "    SERVER_NAME       (сейчас: $(grep '^SERVER_NAME=' .env | cut -d= -f2))"
echo "    PUBLIC_BASE_URL   (сейчас: $(grep '^PUBLIC_BASE_URL=' .env | cut -d= -f2))"
echo
echo "Дальше:  docker compose up -d"
