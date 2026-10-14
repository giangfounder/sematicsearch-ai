#!/usr/bin/env bash
# Sao lưu DB cục bộ (.localpg) ra file để mang lên server. Chạy: bash scripts/dump_local.sh
set -e
URL=$(grep -E '^DATABASE_URL=' .env | cut -d= -f2-)
echo "Dumping $URL -> reports/semsearch_dump.sql"
pg_dump "$URL" --no-owner --no-privileges -f reports/semsearch_dump.sql
echo "Xong. Trên server: docker compose exec -T db psql -U semsearch semsearch < semsearch_dump.sql"
