from __future__ import annotations

import os
import socket
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .archive import Archive, default_archive_root
from .web import serve


DEFAULT_PORT = 8765
MAX_PORT_ATTEMPTS = 10


def _is_archive_server(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=0.7) as response:
            server = response.headers.get("Server", "")
            return "SecondBrainArchive" in server
    except (OSError, urllib.error.URLError):
        return False


def _available_port(host: str = "127.0.0.1") -> int:
    for port in range(DEFAULT_PORT, DEFAULT_PORT + MAX_PORT_ATTEMPTS):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            try:
                candidate.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError("로컬 서버에 사용할 포트를 찾지 못했습니다.")


def _configure_packaged_log(root: Path) -> None:
    if not getattr(sys, "frozen", False):
        return
    log_directory = root / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    stream = (log_directory / "application.log").open(
        "a",
        encoding="utf-8",
        buffering=1,
    )
    sys.stdout = stream
    sys.stderr = stream


def main() -> int:
    root = default_archive_root()
    _configure_packaged_log(root)

    preferred_url = f"http://127.0.0.1:{DEFAULT_PORT}/"
    if _is_archive_server(preferred_url):
        webbrowser.open(preferred_url)
        return 0

    port = int(os.environ.get("SECOND_BRAIN_PORT") or _available_port())
    url = f"http://127.0.0.1:{port}/"
    opener = threading.Timer(1.0, webbrowser.open, args=(url,))
    opener.daemon = True
    opener.start()
    serve(Archive(root), host="127.0.0.1", port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
