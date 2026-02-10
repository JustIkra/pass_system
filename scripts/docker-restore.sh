#!/bin/bash
# Восстанавливает дамп БД при первом запуске postgres контейнера
# Запускается автоматически через /docker-entrypoint-initdb.d/

set -e

DUMP_FILE="/docker-entrypoint-initdb.d/backup.dump"

if [ -f "$DUMP_FILE" ]; then
    echo "Restoring database from backup.dump..."
    pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges "$DUMP_FILE" || true
    echo "Database restore completed."
else
    echo "No backup.dump found, starting with empty database."
fi
