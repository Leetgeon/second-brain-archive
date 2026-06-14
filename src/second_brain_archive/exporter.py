from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .ai import Answer
from .archive import Archive, ArchiveItem


def export_item_markdown(archive: Archive, item: ArchiveItem) -> Path:
    chunks = archive.chunks_for_item(item.id)
    slug = _slug(item.title)
    destination = archive.root / "exports" / f"{slug}-{item.id[:8]}.md"
    lines = [
        "---",
        f'title: "{item.title.replace(chr(34), chr(39))}"',
        f"source: {item.source_url or ''}",
        f"creator: {item.creator or ''}",
        f"playlist: {item.playlist or ''}",
        f"rights: {item.rights_status}",
        f"archived_at: {item.created_at}",
        "tags:",
        "  - second-brain",
        "  - archived-content",
        "---",
        "",
        f"# {item.title}",
        "",
    ]
    if item.source_url:
        lines.append(f"- 원본: {item.source_url}")
    if item.creator:
        lines.append(f"- 제작자: {item.creator}")
    if item.published_at:
        lines.append(f"- 공개일: {item.published_at}")
    lines.extend(["", "## Transcript", ""])
    for chunk in chunks:
        seconds = int(chunk.start_seconds)
        timestamp = (
            f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
        )
        source = _timestamp_url(item.source_url, seconds)
        label = f"[{timestamp}]({source})" if source else timestamp
        lines.append(f"### {label}")
        lines.extend(["", chunk.text, ""])
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return destination


def export_items_markdown(
    archive: Archive,
    items: list[ArchiveItem],
    title: str,
) -> Path:
    if not items:
        raise ValueError("내보낼 자료가 없습니다.")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = (
        archive.root / "exports" / f"collection-{_slug(title)}-{timestamp}.md"
    )
    lines = [
        "---",
        f'title: "{title.replace(chr(34), chr(39))}"',
        f"item_count: {len(items)}",
        f"exported_at: {datetime.now().isoformat(timespec='seconds')}",
        "tags:",
        "  - second-brain",
        "  - content-collection",
        "---",
        "",
        f"# {title}",
        "",
        f"> 총 {len(items)}개 자료를 하나의 Markdown으로 내보냈습니다.",
        "",
        "## 포함 자료",
        "",
    ]
    for index, item in enumerate(items, start=1):
        label = item.title.replace("\n", " ")
        if item.source_url:
            lines.append(f"{index}. [{label}]({item.source_url})")
        else:
            lines.append(f"{index}. {label}")

    for index, item in enumerate(items, start=1):
        chunks = archive.chunks_for_item(item.id)
        lines.extend(["", "---", "", f"## {index}. {item.title}", ""])
        if item.source_url:
            lines.append(f"- 원본: {item.source_url}")
        if item.creator:
            lines.append(f"- 제작자: {item.creator}")
        if item.playlist:
            lines.append(f"- 재생목록: {item.playlist}")
        if item.published_at:
            lines.append(f"- 공개일: {item.published_at}")
        lines.extend(["", "### Transcript", ""])
        if not chunks:
            lines.extend(["_저장된 자막이 없습니다._", ""])
            continue
        for chunk in chunks:
            seconds = int(chunk.start_seconds)
            timestamp_label = (
                f"{seconds // 3600:02d}:"
                f"{(seconds % 3600) // 60:02d}:"
                f"{seconds % 60:02d}"
            )
            source = _timestamp_url(item.source_url, seconds)
            label = (
                f"[{timestamp_label}]({source})" if source else timestamp_label
            )
            lines.extend([f"#### {label}", "", chunk.text, ""])

    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return destination


def export_answer_markdown(
    archive: Archive, question: str, answer: Answer
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = archive.root / "exports" / f"research-{timestamp}.md"
    lines = [
        f"# {question}",
        "",
        f"> Model: `{answer.model}`",
        "",
        answer.text,
        "",
        "## Sources",
        "",
    ]
    for index, hit in enumerate(answer.sources, start=1):
        url = hit.timestamp_url or hit.source_url or ""
        source = f"[{hit.title} - {hit.timestamp}]({url})" if url else hit.title
        lines.extend([f"{index}. {source}", f"   {hit.text}", ""])
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return destination


def _slug(value: str) -> str:
    slug = re.sub(r"[^\w가-힣]+", "-", value.lower(), flags=re.UNICODE).strip("-")
    return slug[:60] or "item"


def _timestamp_url(url: str | None, seconds: int) -> str | None:
    if not url:
        return None
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}t={seconds}s"
