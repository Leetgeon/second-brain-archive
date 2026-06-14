#!/bin/zsh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT_DIR"

(sleep 1; open "http://127.0.0.1:8765") &
exec "$ROOT_DIR/scripts/run.sh"
