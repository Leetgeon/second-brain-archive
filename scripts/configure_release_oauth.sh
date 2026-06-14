#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: $0 /path/to/desktop-oauth-client.json" >&2
  exit 2
fi

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE=$1
TARGET="$ROOT_DIR/src/second_brain_archive/youtube_oauth.json"

python3 - "$SOURCE" <<'PY'
import json
import sys
from pathlib import Path

source = Path(sys.argv[1]).expanduser()
data = json.loads(source.read_text(encoding="utf-8"))
client = data.get("installed")
if not isinstance(client, dict) or not client.get("client_id"):
    raise SystemExit("데스크톱 앱 유형의 Google OAuth JSON이 아닙니다.")
print(f"OAuth client 확인: {client['client_id']}")
PY

cp "$SOURCE" "$TARGET"
chmod 600 "$TARGET"
echo "배포용 OAuth 설정 완료: $TARGET"
