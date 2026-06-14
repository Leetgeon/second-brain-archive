#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  DEFAULT_PYTHON="$ROOT_DIR/.venv/bin/python"
else
  DEFAULT_PYTHON="/Users/mac/.pyenv/versions/3.12.13/bin/python"
fi
PYTHON=${PYTHON:-$DEFAULT_PYTHON}

cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" -m second_brain_archive --root "$ROOT_DIR/data" serve "$@"
