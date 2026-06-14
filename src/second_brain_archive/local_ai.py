from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


DEFAULT_OLLAMA_MODEL = "gemma3:4b-it-qat"
OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
SUPPORTED_MODELS = {
    "gemma3:4b-it-qat": ("Gemma 3 4B QAT", "약 3.3GB · 균형형 권장"),
    "llama3.1:8b": ("Llama 3.1 8B", "약 4.9GB · 더 높은 정확도"),
    "qwen3:4b": ("Qwen 3 4B", "약 2.5GB · 빠른 응답"),
    "granite4:3b": ("Granite 4 3B", "약 2GB · 가벼운 실행"),
}


@dataclass(frozen=True)
class LocalAIStatus:
    installed: bool
    running: bool
    models: tuple[str, ...]
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.running and bool(self.models)


class OllamaRuntime:
    def __init__(self, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")

    def status(self, timeout: float = 1.5) -> LocalAIStatus:
        installed = bool(self._command_path() or self._application_path())
        request = urllib.request.Request(
            f"{self.base_url}/api/tags",
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError, TimeoutError) as error:
            return LocalAIStatus(
                installed=installed,
                running=False,
                models=(),
                error=str(error),
            )
        models = tuple(
            sorted(
                {
                    str(item.get("name") or item.get("model"))
                    for item in payload.get("models", [])
                    if item.get("name") or item.get("model")
                }
            )
        )
        return LocalAIStatus(
            installed=True,
            running=True,
            models=models,
        )

    def start(self, timeout: float = 20.0) -> str:
        status = self.status()
        if status.running:
            return "Ollama가 이미 실행 중입니다."

        application = self._application_path()
        command = self._command_path()
        if platform.system() == "Darwin" and application:
            subprocess.Popen(
                ["/usr/bin/open", "-a", "Ollama"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif command:
            arguments = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "start_new_session": True,
            }
            if platform.system() == "Windows":
                arguments["creationflags"] = getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                )
            subprocess.Popen([command, "serve"], **arguments)
        else:
            raise RuntimeError(
                "Ollama가 설치되지 않았습니다. 공식 설치 파일을 먼저 설치하세요."
            )

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status(timeout=1).running:
                return "Ollama를 실행했습니다."
            time.sleep(0.5)
        raise RuntimeError("Ollama를 실행했지만 로컬 API가 준비되지 않았습니다.")

    def pull_model(self, model: str = DEFAULT_OLLAMA_MODEL) -> str:
        if model not in SUPPORTED_MODELS:
            raise ValueError(f"지원하지 않는 모델입니다: {model}")
        if not self.status().running:
            raise RuntimeError("먼저 Ollama를 실행하세요.")
        payload = json.dumps(
            {"model": model, "stream": False}
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/pull",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=3600) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama 모델 다운로드가 실패했습니다: HTTP {error.code} {detail}"
            ) from error
        except (OSError, ValueError, urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"Ollama 모델 다운로드가 실패했습니다: {error}") from error
        if result.get("status") != "success":
            raise RuntimeError(f"Ollama가 완료 상태를 반환하지 않았습니다: {result}")
        return f"{model} 모델 다운로드를 완료했습니다."

    @staticmethod
    def label(model: str) -> str:
        return SUPPORTED_MODELS.get(model, (model, ""))[0]

    @staticmethod
    def description(model: str) -> str:
        return SUPPORTED_MODELS.get(model, ("", ""))[1]

    @staticmethod
    def choose_model(
        models: tuple[str, ...],
        preferred: str = DEFAULT_OLLAMA_MODEL,
    ) -> str | None:
        if preferred in models:
            return preferred
        if DEFAULT_OLLAMA_MODEL in models:
            return DEFAULT_OLLAMA_MODEL
        return models[0] if models else None

    @staticmethod
    def _command_path() -> str | None:
        command = shutil.which("ollama")
        if command:
            return command
        if platform.system() != "Windows":
            return None
        candidates = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "Ollama"
            / "ollama.exe",
            Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe",
        )
        return str(next((path for path in candidates if path.is_file()), "")) or None

    @staticmethod
    def _application_path() -> Path | None:
        candidates = (
            Path("/Applications/Ollama.app"),
            Path.home() / "Applications" / "Ollama.app",
        )
        return next((path for path in candidates if path.exists()), None)
