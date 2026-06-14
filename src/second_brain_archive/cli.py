from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .ai import OllamaAssistant
from .archive import Archive, RIGHTS_STATUSES, default_archive_root, items_as_dicts
from .downloader import DownloadOptions, Downloader
from .exporter import export_answer_markdown, export_item_markdown
from .local_ai import DEFAULT_OLLAMA_MODEL, OllamaRuntime
from .runtime import ffmpeg_executable, find_executable
from .subtitles import make_chunks, parse_subtitle
from .transcriber import Transcriber
from .web import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="second-brain",
        description="Download, archive, search, and question saved content.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_archive_root(),
        help="Archive root (default: SECOND_BRAIN_HOME or the platform app data folder)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize an archive")
    subparsers.add_parser("doctor", help="Check local dependencies")
    subparsers.add_parser("verify", help="Verify database and archived media hashes")
    subparsers.add_parser("setup-whisper", help="Download the Whisper small model")

    add_url = subparsers.add_parser("add-url", help="Register a source URL")
    add_url.add_argument("url")
    add_url.add_argument("--title")
    add_url.add_argument("--platform")
    add_url.add_argument("--playlist")
    add_url.add_argument("--rights", choices=RIGHTS_STATUSES, default="reference")
    add_url.add_argument("--rights-note")

    download = subparsers.add_parser(
        "download", help="Download one URL or playlist with yt-dlp"
    )
    download.add_argument("url")
    download.add_argument("--playlist")
    download.add_argument("--max-height", type=int, default=1080)
    download.add_argument("--sub-langs", default="ko.*,ko,en.*,en")
    download.add_argument("--audio-only", action="store_true")
    download.add_argument("--subtitles-only", action="store_true")
    download.add_argument("--no-subs", action="store_true")
    download.add_argument("--no-transcribe", action="store_true")
    download.add_argument("--rights", choices=RIGHTS_STATUSES, default="personal-use")

    import_file = subparsers.add_parser(
        "import-file", help="Copy a local file into the archive"
    )
    import_file.add_argument("path", type=Path)
    import_file.add_argument("--title")
    import_file.add_argument("--source-url")
    import_file.add_argument("--platform")
    import_file.add_argument("--playlist")
    import_file.add_argument(
        "--rights",
        choices=("owned", "licensed", "public-domain", "personal-use"),
        required=True,
    )
    import_file.add_argument("--rights-note")
    import_file.add_argument("--transcript", type=Path)

    transcribe = subparsers.add_parser(
        "transcribe", help="Transcribe one archived media item"
    )
    transcribe.add_argument("item_id")
    transcribe.add_argument("--language", default="auto")

    search = subparsers.add_parser("search", help="Search transcript contents")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=12)
    search.add_argument("--json", action="store_true")

    ask = subparsers.add_parser("ask", help="Ask a grounded question with Ollama")
    ask.add_argument("question")
    ask.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    ask.add_argument("--json", action="store_true")
    ask.add_argument("--export", action="store_true")

    export = subparsers.add_parser("export", help="Export one item as Markdown")
    export.add_argument("item_id")

    list_parser = subparsers.add_parser("list", help="List archived items")
    list_parser.add_argument("--json", action="store_true")

    show_parser = subparsers.add_parser("show", help="Show one archived item")
    show_parser.add_argument("item_id")
    show_parser.add_argument("--json", action="store_true")

    server = subparsers.add_parser("serve", help="Start the local web dashboard")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--model", default=DEFAULT_OLLAMA_MODEL)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    archive = Archive(args.root)

    try:
        if args.command == "init":
            archive.initialize()
            print(f"Initialized archive: {archive.root}")
            return 0

        archive.initialize()

        if args.command == "doctor":
            return _doctor(archive)

        if args.command == "verify":
            report = archive.verify()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ok"] else 1

        if args.command == "setup-whisper":
            path = Transcriber(archive).ensure_model(download=True)
            print(f"Whisper model ready: {path}")
            return 0

        if args.command == "add-url":
            item = archive.add_url(
                url=args.url,
                title=args.title or args.url,
                rights_status=args.rights,
                platform=args.platform,
                playlist=args.playlist,
                rights_note=args.rights_note,
            )
            print(f"Registered {item.id}: {item.title}")
            return 0

        if args.command == "download":
            if args.subtitles_only and (args.audio_only or args.no_subs):
                parser.error("--subtitles-only cannot be combined with --audio-only or --no-subs")
            options = DownloadOptions(
                playlist=args.playlist,
                rights_status=args.rights,
                max_height=args.max_height,
                subtitle_languages=args.sub_langs,
                audio_only=args.audio_only,
                download_subtitles=not args.no_subs,
                subtitles_only=args.subtitles_only,
                transcribe_missing=not args.no_transcribe and not args.subtitles_only,
            )
            transcriber = (
                Transcriber(archive)
                if options.transcribe_missing
                else None
            )
            result = Downloader(archive).download(
                args.url, options=options, transcriber=transcriber
            )
            for item in result.items:
                print(f"Archived {item.id}: {item.title}")
            if not result.items:
                print("No new items downloaded.")
            return 0

        if args.command == "import-file":
            item = archive.import_file(
                source=args.path,
                title=args.title,
                rights_status=args.rights,
                source_url=args.source_url,
                platform=args.platform,
                playlist=args.playlist,
                rights_note=args.rights_note,
                transcript=args.transcript,
            )
            if args.transcript:
                archive.index_segments(
                    item.id, make_chunks(parse_subtitle(args.transcript))
                )
            print(f"Imported {item.id}: {item.title}")
            return 0

        if args.command == "transcribe":
            item = Transcriber(archive, language=args.language).transcribe_item(
                args.item_id
            )
            print(f"Transcribed {item.id}: {item.title}")
            return 0

        if args.command == "search":
            hits = archive.search(args.query, limit=args.limit)
            if args.json:
                print(
                    json.dumps(
                        [asdict(hit) for hit in hits],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                for hit in hits:
                    print(f"{hit.timestamp}\t{hit.title}\t{hit.text}")
                    if hit.timestamp_url:
                        print(f"  {hit.timestamp_url}")
            return 0

        if args.command == "ask":
            answer = OllamaAssistant(archive, model=args.model).ask(args.question)
            if args.json:
                print(
                    json.dumps(
                        {
                            "answer": answer.text,
                            "model": answer.model,
                            "sources": [asdict(hit) for hit in answer.sources],
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(answer.text)
                for index, hit in enumerate(answer.sources, start=1):
                    print(
                        f"[{index}] {hit.title} {hit.timestamp} "
                        f"{hit.timestamp_url or ''}"
                    )
            if args.export:
                print(f"Exported: {export_answer_markdown(archive, args.question, answer)}")
            return 0

        if args.command == "export":
            item = archive.get_item(args.item_id)
            if item is None:
                print(f"Item not found: {args.item_id}", file=sys.stderr)
                return 1
            print(f"Exported: {export_item_markdown(archive, item)}")
            return 0

        if args.command == "list":
            items = archive.list_items()
            if args.json:
                print(json.dumps(items_as_dicts(items), ensure_ascii=False, indent=2))
            else:
                for item in items:
                    print(
                        f"{item.id}\t{item.status}\t{item.rights_status}\t{item.title}"
                    )
            return 0

        if args.command == "show":
            item = archive.get_item(args.item_id)
            if item is None:
                print(f"Item not found: {args.item_id}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(asdict(item), ensure_ascii=False, indent=2))
            else:
                for key, value in asdict(item).items():
                    print(f"{key}: {value}")
            return 0

        if args.command == "serve":
            serve(
                archive,
                host=args.host,
                port=args.port,
                ollama_model=args.model,
            )
            return 0
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    parser.error(f"Unknown command: {args.command}")
    return 2


def _doctor(archive: Archive) -> int:
    checks = {
        "yt-dlp": find_executable("yt-dlp") or "embedded Python package",
        "ffmpeg": ffmpeg_executable(),
        "whisper-cli": find_executable("whisper-cli"),
        "whisper-model": (
            str(Transcriber(archive).model_path)
            if Transcriber(archive).model_path.is_file()
            else None
        ),
    }
    ollama_status = OllamaRuntime().status(timeout=2)
    checks["ollama"] = (
        f"{len(ollama_status.models)} model(s)"
        if ollama_status.running
        else None
    )

    for name, value in checks.items():
        print(f"{'OK' if value else 'MISSING':7} {name}: {value or '-'}")
    return 0 if all(checks.values()) else 1
