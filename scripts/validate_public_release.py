#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from second_brain_archive.public_info import public_info


def main() -> int:
    errors = public_info().validation_errors()
    oauth_path = Path("src/second_brain_archive/youtube_oauth_public.json")
    if not oauth_path.is_file():
        errors.append("youtube_oauth_public.json")
    if errors:
        raise SystemExit(
            "Missing public release configuration: " + ", ".join(errors)
        )
    print("Public release configuration is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
