#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 /path/to/backup-directory" >&2
  exit 2
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE="$ROOT_DIR/data/"
DESTINATION=$1
STAMP=$(date +%Y%m%d-%H%M%S)
TARGET="$DESTINATION/second-brain-$STAMP"

mkdir -p "$TARGET"
rsync -a --delete --exclude "secrets/" "$SOURCE" "$TARGET/data/"
cp "$ROOT_DIR/README.md" "$TARGET/README.md"
echo "Backup complete: $TARGET"
