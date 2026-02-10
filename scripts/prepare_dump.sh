#!/bin/bash
# Подготавливает дамп локальной БД для Docker
# Запускать на локальной машине ПОСЛЕ init_db.py и generate_forecast.py

set -e

echo "Creating database dump..."
pg_dump -U mfc_user -h localhost -p 5432 -Fc mfc_db > backup.dump
echo "Dump created: backup.dump ($(du -h backup.dump | cut -f1))"
echo ""
echo "Now run: docker compose up --build"
