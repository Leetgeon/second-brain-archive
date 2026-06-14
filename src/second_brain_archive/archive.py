from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


RIGHTS_STATUSES = (
    "owned",
    "licensed",
    "public-domain",
    "personal-use",
    "reference",
    "unknown",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_archive_root() -> Path:
    configured = os.environ.get("SECOND_BRAIN_HOME")
    if configured:
        return Path(configured).expanduser()

    packaged = bool(
        getattr(sys, "frozen", False)
        or os.environ.get("SECOND_BRAIN_PACKAGED") == "1"
    )
    if not packaged:
        return Path.cwd() / "data"

    system = platform.system()
    if system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        base = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        )
    else:
        base = Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
        )
    return base / "Second Brain Archive"


@dataclass(frozen=True)
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class ArchiveItem:
    id: str
    external_id: str | None
    title: str
    kind: str
    source_url: str | None
    platform: str | None
    creator: str | None
    playlist: str | None
    rights_status: str
    rights_note: str | None
    media_sha256: str | None
    media_path: str | None
    transcript_path: str | None
    thumbnail_path: str | None
    description_path: str | None
    published_at: str | None
    duration_seconds: float | None
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SearchHit:
    item_id: str
    title: str
    source_url: str | None
    start_seconds: float
    end_seconds: float
    text: str
    score: float

    @property
    def timestamp(self) -> str:
        seconds = max(0, int(self.start_seconds))
        return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    @property
    def timestamp_url(self) -> str | None:
        if not self.source_url:
            return None
        separator = "&" if "?" in self.source_url else "?"
        return f"{self.source_url}{separator}t={int(self.start_seconds)}s"


class Archive:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.database_path = self.root / "catalog.sqlite3"

    def initialize(self) -> None:
        for directory in (
            "media",
            "transcripts",
            "thumbnails",
            "descriptions",
            "records",
            "derivatives",
            "exports",
            "models",
            "staging",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    external_id TEXT,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    source_url TEXT,
                    platform TEXT,
                    creator TEXT,
                    playlist TEXT,
                    rights_status TEXT NOT NULL,
                    rights_note TEXT,
                    media_sha256 TEXT,
                    media_path TEXT,
                    transcript_path TEXT,
                    thumbnail_path TEXT,
                    description_path TEXT,
                    published_at TEXT,
                    duration_seconds REAL,
                    status TEXT NOT NULL DEFAULT 'registered',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._migrate_items(connection)
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    start_seconds REAL NOT NULL,
                    end_seconds REAL NOT NULL,
                    text TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    item_id UNINDEXED,
                    chunk_id UNINDEXED,
                    text,
                    tokenize='unicode61'
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_source_url ON items(source_url)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_external_id ON items(external_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_media_sha256 ON items(media_sha256)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_item_id ON chunks(item_id)"
            )

    def add_url(
        self,
        url: str,
        title: str,
        rights_status: str = "reference",
        platform: str | None = None,
        playlist: str | None = None,
        rights_note: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArchiveItem:
        self._require_initialized()
        self._validate_rights(rights_status)

        normalized_url = url.strip()
        if not normalized_url:
            raise ValueError("URL cannot be empty")

        existing = self.find_by_source_url(normalized_url)
        if existing is not None:
            return existing

        now = utc_now()
        item = ArchiveItem(
            id=str(uuid.uuid4()),
            external_id=None,
            title=title.strip() or normalized_url,
            kind="url",
            source_url=normalized_url,
            platform=platform,
            creator=None,
            playlist=playlist,
            rights_status=rights_status,
            rights_note=rights_note,
            media_sha256=None,
            media_path=None,
            transcript_path=None,
            thumbnail_path=None,
            description_path=None,
            published_at=None,
            duration_seconds=None,
            status="registered",
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self._connect() as connection:
            self._insert(connection, item)
        self._write_manifest(item)
        return item

    def import_file(
        self,
        source: Path | str,
        title: str | None,
        rights_status: str,
        source_url: str | None = None,
        platform: str | None = None,
        playlist: str | None = None,
        rights_note: str | None = None,
        transcript: Path | str | None = None,
        metadata: dict[str, Any] | None = None,
        external_id: str | None = None,
        creator: str | None = None,
        thumbnail: Path | str | None = None,
        description: Path | str | None = None,
        published_at: str | None = None,
        duration_seconds: float | None = None,
    ) -> ArchiveItem:
        self._require_initialized()
        self._validate_rights(rights_status)
        if rights_status in {"reference", "unknown"}:
            raise ValueError(
                "Files may only be imported as owned, licensed, public-domain, "
                "or personal-use"
            )

        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Media file not found: {source_path}")

        media_sha256 = self._sha256(source_path)
        suffix = source_path.suffix.lower()
        relative_media = Path("media") / media_sha256[:2] / f"{media_sha256}{suffix}"
        self._copy_once(source_path, relative_media)

        existing = None
        if source_url:
            existing = self.find_by_source_url(source_url)
        if existing is None and external_id:
            existing = self.find_by_external_id(external_id, platform)

        item_id = existing.id if existing else str(uuid.uuid4())
        created_at = existing.created_at if existing else utc_now()
        relative_transcript = self._copy_attachment(
            transcript, "transcripts", item_id
        )
        relative_thumbnail = self._copy_attachment(
            thumbnail, "thumbnails", item_id
        )
        relative_description = self._copy_attachment(
            description, "descriptions", item_id
        )
        merged_metadata = dict(existing.metadata) if existing else {}
        merged_metadata.update({"original_filename": source_path.name, **(metadata or {})})

        item = ArchiveItem(
            id=item_id,
            external_id=external_id or (existing.external_id if existing else None),
            title=(title or source_path.stem).strip(),
            kind="download" if source_url else "file",
            source_url=source_url or (existing.source_url if existing else None),
            platform=platform or (existing.platform if existing else None),
            creator=creator or (existing.creator if existing else None),
            playlist=playlist or (existing.playlist if existing else None),
            rights_status=rights_status,
            rights_note=rights_note or (existing.rights_note if existing else None),
            media_sha256=media_sha256,
            media_path=relative_media.as_posix(),
            transcript_path=(
                relative_transcript.as_posix()
                if relative_transcript
                else (existing.transcript_path if existing else None)
            ),
            thumbnail_path=(
                relative_thumbnail.as_posix()
                if relative_thumbnail
                else (existing.thumbnail_path if existing else None)
            ),
            description_path=(
                relative_description.as_posix()
                if relative_description
                else (existing.description_path if existing else None)
            ),
            published_at=published_at or (existing.published_at if existing else None),
            duration_seconds=(
                duration_seconds
                if duration_seconds is not None
                else (existing.duration_seconds if existing else None)
            ),
            status="ready" if transcript or (existing and existing.transcript_path) else "media",
            created_at=created_at,
            updated_at=utc_now(),
            metadata=merged_metadata,
        )
        with self._connect() as connection:
            if existing:
                self._update(connection, item)
            else:
                self._insert(connection, item)
        self._write_manifest(item)
        return item

    def attach_transcript(
        self,
        item_id: str,
        transcript: Path | str,
        segments: Sequence[TranscriptSegment],
    ) -> ArchiveItem:
        item = self.get_item(item_id)
        if item is None:
            raise ValueError(f"Item not found: {item_id}")
        relative_transcript = self._copy_attachment(
            transcript, "transcripts", item_id
        )
        if relative_transcript is None:
            raise ValueError("Transcript path is required")

        updated = ArchiveItem(
            **{
                **asdict(item),
                "transcript_path": relative_transcript.as_posix(),
                "status": "ready",
                "updated_at": utc_now(),
            }
        )
        with self._connect() as connection:
            self._update(connection, updated)
            self._replace_chunks(connection, item_id, segments)
        self._write_manifest(updated)
        return updated

    def index_segments(
        self, item_id: str, segments: Sequence[TranscriptSegment]
    ) -> None:
        if self.get_item(item_id) is None:
            raise ValueError(f"Item not found: {item_id}")
        with self._connect() as connection:
            self._replace_chunks(connection, item_id, segments)

    def search(self, query: str, limit: int = 12) -> list[SearchHit]:
        self._require_initialized()
        clean_query = " ".join(query.strip().split())
        if not clean_query:
            return []
        term_groups = self._search_term_groups(clean_query)
        terms = [term for group in term_groups for term in group]
        fts_query = " OR ".join(f'"{term}"' for term in terms)
        candidate_limit = max(limit * 8, limit)

        with self._connect() as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT
                        c.item_id,
                        i.title,
                        i.source_url,
                        c.start_seconds,
                        c.end_seconds,
                        c.text,
                        bm25(chunks_fts) AS score
                    FROM chunks_fts
                    JOIN chunks c ON c.id = CAST(chunks_fts.chunk_id AS INTEGER)
                    JOIN items i ON i.id = c.item_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (fts_query, candidate_limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                clauses = " OR ".join("c.text LIKE ?" for _ in terms)
                parameters = [f"%{term}%" for term in terms]
                rows = connection.execute(
                    f"""
                    SELECT
                        c.item_id,
                        i.title,
                        i.source_url,
                        c.start_seconds,
                        c.end_seconds,
                        c.text,
                        0.0 AS score
                    FROM chunks c
                    JOIN items i ON i.id = c.item_id
                    WHERE {clauses}
                    ORDER BY c.start_seconds
                    LIMIT ?
                    """,
                    (*parameters, candidate_limit),
                ).fetchall()

        available_groups = [
            group
            for group in term_groups
            if any(
                any(term.casefold() in row["text"].casefold() for term in group)
                for row in rows
            )
        ]
        if term_groups[0] not in available_groups:
            return []
        minimum_matches = 2 if len(available_groups) >= 2 else 1
        ranked_rows = []
        for row in rows:
            text = row["text"].casefold()
            group_matches = [
                any(term.casefold() in text for term in group)
                for group in term_groups
            ]
            if not group_matches[0]:
                continue
            matched_groups = sum(group_matches)
            if matched_groups >= minimum_matches:
                ranked_rows.append((matched_groups, row))
        ranked_rows.sort(key=lambda entry: (-entry[0], entry[1]["score"]))

        return [
            SearchHit(
                item_id=row["item_id"],
                title=row["title"],
                source_url=row["source_url"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                text=row["text"],
                score=row["score"],
            )
            for _, row in ranked_rows[:limit]
        ]

    @staticmethod
    def _search_terms(query: str) -> list[str]:
        return [
            term
            for group in Archive._search_term_groups(query)
            for term in group
        ]

    @staticmethod
    def _search_term_groups(query: str) -> list[tuple[str, ...]]:
        stopwords = {
            "않은",
            "없는",
            "건가요",
            "보관한",
            "보관하지",
            "관련",
            "그리고",
            "대한",
            "대해서",
            "어려운",
            "이유",
            "해결",
            "방법",
            "무엇",
            "무엇인가요",
            "설명",
            "저장한",
            "저장하지",
            "알려",
            "알려줘",
            "알려주세요",
            "어떤",
            "어떻게",
            "왜",
            "인가요",
            "있나요",
            "질문",
            "해주세요",
        }
        suffixes = (
            "에서는",
            "으로는",
            "에게서",
            "에서",
            "으로",
            "에게",
            "까지",
            "부터",
            "처럼",
            "보다",
            "라서",
            "해서",
            "하고",
            "이며",
            "이고",
            "께서",
            "은",
            "는",
            "이",
            "가",
            "을",
            "를",
            "의",
            "에",
            "와",
            "과",
            "도",
            "만",
            "로",
        )
        groups: list[tuple[str, ...]] = []
        for token in re.findall(r"[0-9A-Za-z가-힣]{2,}", query):
            if token.startswith("무엇"):
                continue
            candidates = [token]
            for suffix in suffixes:
                if token.endswith(suffix) and len(token) - len(suffix) >= 2:
                    candidates.append(token[: -len(suffix)])
                    break
            if any(candidate in stopwords for candidate in candidates):
                continue
            group = tuple(
                candidate
                for candidate in dict.fromkeys(candidates)
            )
            if group and group not in groups:
                groups.append(group)
        return groups[:12] or [(query,)]

    def list_items(
        self, playlist: str | None = None, status: str | None = None
    ) -> list[ArchiveItem]:
        self._require_initialized()
        clauses: list[str] = []
        parameters: list[Any] = []
        if playlist:
            clauses.append("playlist = ?")
            parameters.append(playlist)
        if status:
            clauses.append("status = ?")
            parameters.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM items {where} ORDER BY updated_at DESC, id",
                parameters,
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def get_item(self, item_id: str) -> ArchiveItem | None:
        self._require_initialized()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def delete_google_authorized_items(self) -> int:
        self._require_initialized()
        items = [
            item
            for item in self.list_items()
            if item.metadata.get("google_authorized_data") is True
        ]
        if not items:
            return 0
        item_ids = [item.id for item in items]
        placeholders = ",".join("?" for _ in item_ids)
        with self._connect() as connection:
            connection.execute(
                f"DELETE FROM chunks_fts WHERE item_id IN ({placeholders})",
                item_ids,
            )
            connection.execute(
                f"DELETE FROM chunks WHERE item_id IN ({placeholders})",
                item_ids,
            )
            connection.execute(
                f"DELETE FROM items WHERE id IN ({placeholders})",
                item_ids,
            )
        for item in items:
            (self.root / "records" / f"{item.id}.json").unlink(missing_ok=True)
        return len(items)

    def find_by_source_url(self, source_url: str) -> ArchiveItem | None:
        self._require_initialized()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM items WHERE source_url = ? ORDER BY created_at LIMIT 1",
                (source_url,),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def find_by_external_id(
        self, external_id: str, platform: str | None = None
    ) -> ArchiveItem | None:
        self._require_initialized()
        query = "SELECT * FROM items WHERE external_id = ?"
        parameters: list[Any] = [external_id]
        if platform:
            query += " AND platform = ?"
            parameters.append(platform)
        query += " ORDER BY created_at LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, parameters).fetchone()
        return self._row_to_item(row) if row is not None else None

    def chunks_for_item(self, item_id: str) -> list[TranscriptSegment]:
        self._require_initialized()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT start_seconds, end_seconds, text
                FROM chunks
                WHERE item_id = ?
                ORDER BY start_seconds, id
                """,
                (item_id,),
            ).fetchall()
        return [
            TranscriptSegment(row["start_seconds"], row["end_seconds"], row["text"])
            for row in rows
        ]

    def recent_chunks(self, limit: int = 8) -> list[SearchHit]:
        self._require_initialized()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    c.item_id,
                    i.title,
                    i.source_url,
                    c.start_seconds,
                    c.end_seconds,
                    c.text
                FROM chunks c
                JOIN items i ON i.id = c.item_id
                ORDER BY i.updated_at DESC, c.start_seconds
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            SearchHit(
                item_id=row["item_id"],
                title=row["title"],
                source_url=row["source_url"],
                start_seconds=row["start_seconds"],
                end_seconds=row["end_seconds"],
                text=row["text"],
                score=0.0,
            )
            for row in rows
        ]

    def stats(self) -> dict[str, int]:
        self._require_initialized()
        with self._connect() as connection:
            item_count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            media_count = connection.execute(
                "SELECT COUNT(*) FROM items WHERE media_path IS NOT NULL"
            ).fetchone()[0]
            transcript_count = connection.execute(
                "SELECT COUNT(*) FROM items WHERE transcript_path IS NOT NULL"
            ).fetchone()[0]
            chunk_count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return {
            "items": item_count,
            "media": media_count,
            "transcripts": transcript_count,
            "chunks": chunk_count,
        }

    def verify(self) -> dict[str, Any]:
        self._require_initialized()
        problems: list[str] = []
        checked_media = 0
        with self._connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            rows = connection.execute(
                """
                SELECT id, media_sha256, media_path
                FROM items
                WHERE media_path IS NOT NULL
                """
            ).fetchall()
        if integrity != "ok":
            problems.append(f"SQLite integrity check: {integrity}")
        for row in rows:
            path = self.absolute_path(row["media_path"])
            if path is None or not path.is_file():
                problems.append(f"{row['id']}: media file is missing")
                continue
            checked_media += 1
            if row["media_sha256"] and self._sha256(path) != row["media_sha256"]:
                problems.append(f"{row['id']}: SHA-256 mismatch")
        return {
            "database": integrity,
            "checked_media": checked_media,
            "problems": problems,
            "ok": not problems,
        }

    def absolute_path(self, relative_path: str | None) -> Path | None:
        return self.root / relative_path if relative_path else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _require_initialized(self) -> None:
        if not self.database_path.is_file():
            raise RuntimeError(
                f"Archive is not initialized at {self.root}. Run 'init' first."
            )

    @staticmethod
    def _validate_rights(rights_status: str) -> None:
        if rights_status not in RIGHTS_STATUSES:
            allowed = ", ".join(RIGHTS_STATUSES)
            raise ValueError(f"Invalid rights status. Choose one of: {allowed}")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _copy_once(self, source: Path, relative_destination: Path) -> None:
        destination = self.root / relative_destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)

    def _copy_attachment(
        self, source: Path | str | None, directory: str, item_id: str
    ) -> Path | None:
        if source is None:
            return None
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Attachment not found: {source_path}")
        suffix = source_path.suffix.lower() or ".txt"
        relative_path = Path(directory) / f"{item_id}{suffix}"
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source_path != destination:
            shutil.copy2(source_path, destination)
        return relative_path

    @staticmethod
    def _migrate_items(connection: sqlite3.Connection) -> None:
        existing = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(items)").fetchall()
        }
        columns = {
            "external_id": "TEXT",
            "creator": "TEXT",
            "thumbnail_path": "TEXT",
            "description_path": "TEXT",
            "published_at": "TEXT",
            "duration_seconds": "REAL",
            "status": "TEXT NOT NULL DEFAULT 'registered'",
            "updated_at": "TEXT",
        }
        for name, definition in columns.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE items ADD COLUMN {name} {definition}")
        connection.execute(
            "UPDATE items SET updated_at = created_at WHERE updated_at IS NULL"
        )

    @staticmethod
    def _insert(connection: sqlite3.Connection, item: ArchiveItem) -> None:
        connection.execute(
            """
            INSERT INTO items (
                id, external_id, title, kind, source_url, platform, creator,
                playlist, rights_status, rights_note, media_sha256, media_path,
                transcript_path, thumbnail_path, description_path, published_at,
                duration_seconds, status, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            Archive._item_values(item),
        )

    @staticmethod
    def _update(connection: sqlite3.Connection, item: ArchiveItem) -> None:
        connection.execute(
            """
            UPDATE items SET
                external_id = ?, title = ?, kind = ?, source_url = ?,
                platform = ?, creator = ?, playlist = ?, rights_status = ?,
                rights_note = ?, media_sha256 = ?, media_path = ?,
                transcript_path = ?, thumbnail_path = ?, description_path = ?,
                published_at = ?, duration_seconds = ?, status = ?,
                created_at = ?, updated_at = ?, metadata_json = ?
            WHERE id = ?
            """,
            (*Archive._item_values(item)[1:], item.id),
        )

    @staticmethod
    def _item_values(item: ArchiveItem) -> tuple[Any, ...]:
        return (
            item.id,
            item.external_id,
            item.title,
            item.kind,
            item.source_url,
            item.platform,
            item.creator,
            item.playlist,
            item.rights_status,
            item.rights_note,
            item.media_sha256,
            item.media_path,
            item.transcript_path,
            item.thumbnail_path,
            item.description_path,
            item.published_at,
            item.duration_seconds,
            item.status,
            item.created_at,
            item.updated_at,
            json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
        )

    @staticmethod
    def _replace_chunks(
        connection: sqlite3.Connection,
        item_id: str,
        segments: Sequence[TranscriptSegment],
    ) -> None:
        old_ids = [
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM chunks WHERE item_id = ?", (item_id,)
            ).fetchall()
        ]
        if old_ids:
            connection.execute(
                f"DELETE FROM chunks_fts WHERE chunk_id IN "
                f"({','.join('?' for _ in old_ids)})",
                old_ids,
            )
        connection.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
        for segment in segments:
            text = " ".join(segment.text.split())
            if not text:
                continue
            cursor = connection.execute(
                """
                INSERT INTO chunks(item_id, start_seconds, end_seconds, text)
                VALUES (?, ?, ?, ?)
                """,
                (item_id, segment.start_seconds, segment.end_seconds, text),
            )
            chunk_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO chunks_fts(item_id, chunk_id, text) VALUES (?, ?, ?)",
                (item_id, str(chunk_id), text),
            )

    def _write_manifest(self, item: ArchiveItem) -> None:
        manifest_path = self.root / "records" / f"{item.id}.json"
        manifest_path.write_text(
            json.dumps(asdict(item), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ArchiveItem:
        keys = set(row.keys())
        created_at = row["created_at"]
        return ArchiveItem(
            id=row["id"],
            external_id=row["external_id"] if "external_id" in keys else None,
            title=row["title"],
            kind=row["kind"],
            source_url=row["source_url"],
            platform=row["platform"],
            creator=row["creator"] if "creator" in keys else None,
            playlist=row["playlist"],
            rights_status=row["rights_status"],
            rights_note=row["rights_note"],
            media_sha256=row["media_sha256"],
            media_path=row["media_path"],
            transcript_path=row["transcript_path"],
            thumbnail_path=row["thumbnail_path"] if "thumbnail_path" in keys else None,
            description_path=(
                row["description_path"] if "description_path" in keys else None
            ),
            published_at=row["published_at"] if "published_at" in keys else None,
            duration_seconds=(
                row["duration_seconds"] if "duration_seconds" in keys else None
            ),
            status=row["status"] if "status" in keys else "registered",
            created_at=created_at,
            updated_at=(
                row["updated_at"]
                if "updated_at" in keys and row["updated_at"]
                else created_at
            ),
            metadata=json.loads(row["metadata_json"]),
        )


def items_as_dicts(items: Iterable[ArchiveItem]) -> list[dict[str, Any]]:
    return [asdict(item) for item in items]
