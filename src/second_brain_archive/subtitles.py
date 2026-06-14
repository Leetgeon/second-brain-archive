from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable, Sequence

from .archive import TranscriptSegment


TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s+-->\s+"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")
VTT_SETTING_RE = re.compile(r"\s+(?:align|position|size|line|vertical):\S+")


def parse_subtitle(path: Path | str) -> list[TranscriptSegment]:
    subtitle_path = Path(path)
    text = subtitle_path.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0

    while index < len(lines):
        match = TIMESTAMP_RE.search(VTT_SETTING_RE.sub("", lines[index]))
        if not match:
            index += 1
            continue
        start = timestamp_to_seconds(match.group("start"))
        end = timestamp_to_seconds(match.group("end"))
        index += 1
        caption_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            caption_lines.append(clean_caption_line(lines[index]))
            index += 1
        caption = " ".join(line for line in caption_lines if line)
        if caption:
            segments.append(TranscriptSegment(start, end, caption))

    return deduplicate_segments(segments)


def timestamp_to_seconds(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_caption_line(line: str) -> str:
    line = TAG_RE.sub("", line)
    line = html.unescape(line)
    line = re.sub(r"\{\\[^}]+\}", "", line)
    return " ".join(line.split())


def deduplicate_segments(
    segments: Iterable[TranscriptSegment],
) -> list[TranscriptSegment]:
    deduplicated: list[TranscriptSegment] = []
    previous = ""
    for segment in segments:
        text = segment.text.strip()
        if not text or text == previous:
            continue
        if previous and text.startswith(previous):
            text = text[len(previous) :].strip()
        elif previous and previous.endswith(text):
            continue
        if text:
            deduplicated.append(
                TranscriptSegment(segment.start_seconds, segment.end_seconds, text)
            )
            previous = segment.text.strip()
    return deduplicated


def make_chunks(
    segments: Sequence[TranscriptSegment],
    max_characters: int = 900,
    max_duration: float = 90.0,
) -> list[TranscriptSegment]:
    if not segments:
        return []

    chunks: list[TranscriptSegment] = []
    start = segments[0].start_seconds
    end = segments[0].end_seconds
    parts: list[str] = []

    for segment in segments:
        proposed = " ".join((*parts, segment.text))
        too_long = len(proposed) > max_characters
        too_wide = parts and segment.end_seconds - start > max_duration
        if parts and (too_long or too_wide):
            chunks.append(TranscriptSegment(start, end, " ".join(parts)))
            start = segment.start_seconds
            parts = []
        parts.append(segment.text)
        end = segment.end_seconds

    if parts:
        chunks.append(TranscriptSegment(start, end, " ".join(parts)))
    return chunks


def transcript_as_markdown(
    title: str, source_url: str | None, segments: Sequence[TranscriptSegment]
) -> str:
    lines = [f"# {title}", ""]
    if source_url:
        lines.extend([f"Source: {source_url}", ""])
    for segment in segments:
        seconds = int(segment.start_seconds)
        timestamp = (
            f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
        )
        lines.append(f"- **{timestamp}** {segment.text}")
    return "\n".join(lines) + "\n"
