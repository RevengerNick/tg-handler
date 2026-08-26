#!/usr/bin/env sh
set -eu

# Backs up Reader/application databases only. Telegram session auth keys are
# intentionally excluded and must be handled by a separate protected manual backup.
data_dir="${DATA_DIR:-/app/data}"
backup_dir="${TG_READER_BACKUP_DIR:-/app/data/backups}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$backup_dir/$stamp"

mkdir -p "$target"
chmod 700 "$backup_dir" "$target"

for database in telegram_reader.db database.db; do
  if [ -f "$data_dir/$database" ]; then
    python - "$data_dir/$database" "$target/$database" <<'PY'
import sqlite3
import sys

source, destination = sys.argv[1], sys.argv[2]
with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)
PY
    chmod 600 "$target/$database"
  fi
done

find "$data_dir/sessions" -maxdepth 1 -type f -printf '%f\t%s bytes\t%m\n' 2>/dev/null > "$target/session-files.txt" || true
chmod 600 "$target/session-files.txt"
printf '%s\n' "$target"
