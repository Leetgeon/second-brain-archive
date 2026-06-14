from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive import Archive, ArchiveItem
from .runtime import ffmpeg_executable, find_executable
from .subtitles import make_chunks, parse_subtitle


MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".webm",
    ".mov",
    ".m4a",
    ".mp3",
    ".opus",
    ".wav",
    ".flac",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt"}


@dataclass(frozen=True)
class DownloadOptions:
    playlist: str | None = None
    rights_status: str = "personal-use"
    max_height: int = 1080
    subtitle_languages: str = "ko.*,ko,en.*,en"
    audio_only: bool = False
    download_subtitles: bool = True
    subtitles_only: bool = False
    transcribe_missing: bool = True


@dataclass(frozen=True)
class DownloadResult:
    items: list[ArchiveItem]
    command_output: str


class Downloader:
    def __init__(self, archive: Archive) -> None:
        self.archive = archive

    def download(
        self,
        url: str,
        options: DownloadOptions | None = None,
        transcriber: Any | None = None,
    ) -> DownloadResult:
        options = options or DownloadOptions()
        if options.subtitles_only and not options.download_subtitles:
            raise ValueError("Subtitle-only downloads require subtitles to be enabled.")
        executable = find_executable("yt-dlp")

        self.archive.initialize()
        batch_directory = self.archive.root / "staging" / str(uuid.uuid4())
        batch_directory.mkdir(parents=True, exist_ok=True)
        output_template = str(batch_directory / "%(id)s" / "%(id)s.%(ext)s")
        archive_file = self.archive.root / "download-archive.txt"

        command = [
            executable or "yt-dlp",
            "--ignore-errors",
            "--continue",
            "--no-overwrites",
            "--write-info-json",
            "--output",
            output_template,
            "--newline",
        ]
        ffmpeg = ffmpeg_executable()
        if ffmpeg:
            command.extend(["--ffmpeg-location", ffmpeg])
        if options.download_subtitles:
            command.extend(
                [
                    "--write-subs",
                    "--write-auto-subs",
                    "--sub-langs",
                    options.subtitle_languages,
                    "--sub-format",
                    "vtt/srt/best",
                ]
            )
        if options.subtitles_only:
            command.append("--skip-download")
        else:
            command.extend(
                [
                    "--write-description",
                    "--write-thumbnail",
                    "--download-archive",
                    str(archive_file),
                ]
            )
        if not options.subtitles_only:
            if options.audio_only:
                command.extend(["--format", "bestaudio/best", "--extract-audio"])
            else:
                command.extend(
                    [
                        "--format",
                        (
                            f"bv*[height<={options.max_height}]+ba/"
                            f"b[height<={options.max_height}]/best"
                        ),
                        "--merge-output-format",
                        "mp4",
                    ]
                )
        command.append(url)

        process = (
            subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            if executable
            else self._run_embedded(url, output_template, archive_file, options, ffmpeg)
        )
        if process.returncode not in (0, 1):
            raise RuntimeError(
                f"yt-dlp failed with exit code {process.returncode}:\n"
                f"{process.stdout[-4000:]}"
            )

        items: list[ArchiveItem] = []
        for info_path in sorted(batch_directory.rglob("*.info.json")):
            item = (
                self._import_subtitle_download(info_path, options)
                if options.subtitles_only
                else self._import_download(info_path, options)
            )
            if item is None:
                continue
            items.append(item)
            if item.transcript_path:
                transcript_path = self.archive.absolute_path(item.transcript_path)
                if transcript_path:
                    segments = make_chunks(parse_subtitle(transcript_path))
                    self.archive.index_segments(item.id, segments)
            elif options.transcribe_missing and transcriber is not None:
                item = transcriber.transcribe_item(item.id)
                items[-1] = item

        shutil.rmtree(batch_directory, ignore_errors=True)
        if process.returncode != 0 and not items:
            raise RuntimeError(f"yt-dlp could not download the URL:\n{process.stdout[-4000:]}")
        return DownloadResult(items=items, command_output=process.stdout)

    @staticmethod
    def _run_embedded(
        url: str,
        output_template: str,
        archive_file: Path,
        options: DownloadOptions,
        ffmpeg: str | None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError as error:
            raise RuntimeError(
                "영상 다운로드 구성요소를 찾지 못했습니다. 앱을 다시 설치하세요."
            ) from error

        messages: list[str] = []

        class Logger:
            def debug(self, message: str) -> None:
                messages.append(str(message))

            def info(self, message: str) -> None:
                messages.append(str(message))

            def warning(self, message: str) -> None:
                messages.append(f"WARNING: {message}")

            def error(self, message: str) -> None:
                messages.append(f"ERROR: {message}")

        parameters: dict[str, Any] = {
            "ignoreerrors": True,
            "continuedl": True,
            "overwrites": False,
            "writeinfojson": True,
            "outtmpl": output_template,
            "logger": Logger(),
        }
        if ffmpeg:
            parameters["ffmpeg_location"] = ffmpeg
        if options.download_subtitles:
            parameters.update(
                {
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": [
                        language.strip()
                        for language in options.subtitle_languages.split(",")
                        if language.strip()
                    ],
                    "subtitlesformat": "vtt/srt/best",
                }
            )
        if options.subtitles_only:
            parameters["skip_download"] = True
        else:
            parameters.update(
                {
                    "writedescription": True,
                    "writethumbnail": True,
                    "download_archive": str(archive_file),
                }
            )
            if options.audio_only:
                parameters["format"] = "bestaudio/best"
                parameters["postprocessors"] = [{"key": "FFmpegExtractAudio"}]
            else:
                parameters["format"] = (
                    f"bv*[height<={options.max_height}]+ba/"
                    f"b[height<={options.max_height}]/best"
                )
                parameters["merge_output_format"] = "mp4"

        try:
            with YoutubeDL(parameters) as downloader:
                return_code = downloader.download([url])
        except Exception as error:  # yt-dlp raises extractor-specific subclasses
            messages.append(f"ERROR: {error}")
            return_code = 2
        return subprocess.CompletedProcess(
            args=["embedded-yt-dlp", url],
            returncode=return_code,
            stdout="\n".join(messages),
        )

    def _import_subtitle_download(
        self, info_path: Path, options: DownloadOptions
    ) -> ArchiveItem | None:
        metadata = json.loads(info_path.read_text(encoding="utf-8"))
        directory = info_path.parent
        subtitle = self._find_subtitle(directory)
        if subtitle is None:
            return None

        source_url = metadata.get("webpage_url") or metadata.get("original_url")
        external_id = str(metadata.get("id")) if metadata.get("id") else None
        platform = metadata.get("extractor_key") or metadata.get("extractor")
        existing = self.archive.find_by_source_url(source_url) if source_url else None
        if existing is None and external_id:
            existing = self.archive.find_by_external_id(external_id, platform)
        if existing is None:
            if not source_url:
                return None
            existing = self.archive.add_url(
                source_url,
                metadata.get("title") or external_id or source_url,
                rights_status="reference",
                platform=platform,
                playlist=(
                    options.playlist
                    or metadata.get("playlist_title")
                    or metadata.get("playlist")
                ),
                metadata={
                    "subtitle_only": True,
                    "creator": metadata.get("channel") or metadata.get("uploader"),
                },
            )

        segments = make_chunks(parse_subtitle(subtitle))
        return self.archive.attach_transcript(existing.id, subtitle, segments)

    def _import_download(
        self, info_path: Path, options: DownloadOptions
    ) -> ArchiveItem | None:
        metadata = json.loads(info_path.read_text(encoding="utf-8"))
        directory = info_path.parent
        media = self._find_media(directory)
        if media is None:
            return None

        subtitle = self._find_subtitle(directory)
        thumbnail = self._find_first(directory, IMAGE_EXTENSIONS)
        description = self._find_first(directory, {".description"})
        source_url = metadata.get("webpage_url") or metadata.get("original_url")
        platform = metadata.get("extractor_key") or metadata.get("extractor")
        playlist = (
            options.playlist
            or metadata.get("playlist_title")
            or metadata.get("playlist")
        )
        published_at = _normalize_upload_date(metadata.get("upload_date"))

        kept_metadata = {
            key: metadata.get(key)
            for key in (
                "channel",
                "channel_id",
                "uploader_id",
                "view_count",
                "like_count",
                "chapters",
                "language",
                "availability",
                "license",
                "tags",
                "categories",
            )
            if metadata.get(key) is not None
        }

        return self.archive.import_file(
            media,
            title=metadata.get("title") or media.stem,
            rights_status=options.rights_status,
            source_url=source_url,
            platform=platform,
            playlist=playlist,
            rights_note="Downloaded for the user's local personal archive.",
            transcript=subtitle,
            metadata=kept_metadata,
            external_id=str(metadata.get("id")) if metadata.get("id") else None,
            creator=metadata.get("channel") or metadata.get("uploader"),
            thumbnail=thumbnail,
            description=description,
            published_at=published_at,
            duration_seconds=_to_float(metadata.get("duration")),
        )

    @staticmethod
    def _find_media(directory: Path) -> Path | None:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
        ]
        return max(candidates, key=lambda path: path.stat().st_size) if candidates else None

    @staticmethod
    def _find_subtitle(directory: Path) -> Path | None:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix.lower() in SUBTITLE_EXTENSIONS
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda path: (
                0 if ".ko" in path.name.lower() else 1,
                0 if path.suffix.lower() == ".vtt" else 1,
                path.name,
            ),
        )[0]

    @staticmethod
    def _find_first(directory: Path, extensions: set[str]) -> Path | None:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file()
            and (
                path.suffix.lower() in extensions
                or any(path.name.endswith(extension) for extension in extensions)
            )
        ]
        return sorted(candidates)[0] if candidates else None


def _normalize_upload_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _to_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
