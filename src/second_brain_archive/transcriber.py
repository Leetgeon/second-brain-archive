from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from .archive import Archive, ArchiveItem
from .runtime import ffmpeg_executable, find_executable
from .subtitles import make_chunks, parse_subtitle


DEFAULT_MODEL_NAME = "ggml-small.bin"
DEFAULT_MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
)


class Transcriber:
    def __init__(
        self,
        archive: Archive,
        model_path: Path | str | None = None,
        language: str = "auto",
    ) -> None:
        self.archive = archive
        self.model_path = (
            Path(model_path).expanduser().resolve()
            if model_path
            else self.archive.root / "models" / DEFAULT_MODEL_NAME
        )
        self.language = language

    def ensure_model(self, download: bool = False) -> Path:
        if self.model_path.is_file():
            return self.model_path
        if not download:
            raise RuntimeError(
                f"Whisper model not found: {self.model_path}. "
                "Run 'second-brain setup-whisper'."
            )
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.model_path.with_suffix(".part")
        try:
            try:
                urllib.request.urlretrieve(DEFAULT_MODEL_URL, temporary)
            except urllib.error.URLError as error:
                raise RuntimeError(
                    f"Whisper model download failed: {error}"
                ) from error
            temporary.replace(self.model_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return self.model_path

    def transcribe_item(self, item_id: str) -> ArchiveItem:
        item = self.archive.get_item(item_id)
        if item is None:
            raise ValueError(f"Item not found: {item_id}")
        media_path = self.archive.absolute_path(item.media_path)
        if media_path is None or not media_path.is_file():
            raise FileNotFoundError(f"Media is missing for item: {item_id}")

        whisper = find_executable("whisper-cli")
        ffmpeg = ffmpeg_executable()
        if not whisper:
            raise RuntimeError(
                "로컬 Whisper 전사 구성요소가 설치되지 않았습니다. "
                "공개 자막과 자동 자막은 이 구성요소 없이도 저장할 수 있습니다."
            )
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for transcription.")

        model = self.ensure_model(download=False)
        work_directory = self.archive.root / "staging" / f"transcribe-{uuid.uuid4()}"
        work_directory.mkdir(parents=True, exist_ok=True)
        wav_path = work_directory / "audio.wav"
        output_base = work_directory / "transcript"

        convert = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(media_path),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if convert.returncode != 0:
            raise RuntimeError(f"ffmpeg audio extraction failed:\n{convert.stdout}")

        command = [
            whisper,
            "-m",
            str(model),
            "-f",
            str(wav_path),
            "-l",
            self.language,
            "-ovtt",
            "-of",
            str(output_base),
            "-t",
            "6",
        ]
        transcribe = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        vtt_path = output_base.with_suffix(".vtt")
        if transcribe.returncode != 0 and (
            "failed to allocate buffer" in transcribe.stdout
            or transcribe.returncode < 0
        ):
            command.append("-ng")
            transcribe = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if transcribe.returncode != 0 or not vtt_path.is_file():
            raise RuntimeError(
                f"Whisper transcription failed with exit code "
                f"{transcribe.returncode}:\n{transcribe.stdout[-4000:]}"
            )

        segments = make_chunks(parse_subtitle(vtt_path))
        updated = self.archive.attach_transcript(item_id, vtt_path, segments)
        shutil.rmtree(work_directory, ignore_errors=True)
        return updated
