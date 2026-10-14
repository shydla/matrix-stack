#!/bin/sh
# =============================================================================
#  Инициализация БД и ролей. Выполняется автоматически ПРИ ПЕРВОМ старте
#  пустого каталога ./data/postgres. Пароли приходят из .env через окружение
#  контейнера postgres.
# =============================================================================
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    CREATE ROLE ${SYNAPSE_DB_USER} LOGIN PASSWORD '${SYNAPSE_DB_PASSWORD}';
    CREATE DATABASE ${SYNAPSE_DB_NAME}
        OWNER ${SYNAPSE_DB_USER}
        ENCODING 'UTF8'
        LC_COLLATE 'C'
        LC_CTYPE 'C'
        TEMPLATE template0;

    CREATE ROLE ${MAS_DB_USER} LOGIN PASSWORD '${MAS_DB_PASSWORD}';
    CREATE DATABASE ${MAS_DB_NAME}
        OWNER ${MAS_DB_USER}
        ENCODING 'UTF8'
        LC_COLLATE 'C'
        LC_CTYPE 'C'
        TEMPLATE template0;
EOSQL

echo "[initdb] базы готовы: ${SYNAPSE_DB_NAME} (owner ${SYNAPSE_DB_USER}), ${MAS_DB_NAME} (owner ${MAS_DB_USER})"
