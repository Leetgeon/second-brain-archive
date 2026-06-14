#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from second_brain_archive.public_info import public_info


def main() -> int:
    errors = public_info().validation_errors()
    oauth_path = Path("src/second_brain_archive/youtube_oauth.json")
    if not oauth_path.is_file():
        errors.append("YOUTUBE_OAUTH_JSON_BASE64")
    if errors:
        raise SystemExit(
            "공개 릴리스 설정이 누락됐습니다: " + ", ".join(errors)
        )
    print("공개 릴리스 설정 확인 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
