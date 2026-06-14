from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def find_executable(name: str) -> str | None:
    candidates: list[Path] = []
    suffix = ".exe" if platform.system() == "Windows" else ""
    executable_name = name if name.lower().endswith(suffix) else f"{name}{suffix}"

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "bin" / executable_name)

    package_root = Path(__file__).resolve().parent
    candidates.append(package_root / "bin" / executable_name)

    if platform.system() == "Darwin":
        candidates.extend(
            (
                Path("/opt/homebrew/bin") / executable_name,
                Path("/usr/local/bin") / executable_name,
            )
        )

    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which(name)


def ffmpeg_executable() -> str | None:
    external = find_executable("ffmpeg")
    if external:
        return external
    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
    except (ImportError, RuntimeError):
        return None
    return str(bundled) if bundled.is_file() else None
