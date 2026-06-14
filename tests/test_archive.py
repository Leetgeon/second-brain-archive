from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request
from urllib.parse import parse_qs, urlparse

from second_brain_archive.ai import OllamaAssistant
from second_brain_archive.archive import (
    Archive,
    TranscriptSegment,
    default_archive_root,
)
from second_brain_archive.downloader import DownloadOptions, Downloader
from second_brain_archive.distribution import distribution_profile
from second_brain_archive.exporter import export_item_markdown, export_items_markdown
from second_brain_archive.local_ai import DEFAULT_OLLAMA_MODEL, OllamaRuntime
from second_brain_archive.public_info import public_info
from second_brain_archive.subtitles import make_chunks, parse_subtitle
from second_brain_archive.web import (
    _capture_panel,
    _privacy_content,
    _terms_content,
    _youtube_playlist_card,
)
from second_brain_archive.youtube import (
    YouTubeAccount,
    YouTubeAPIError,
    YouTubePlaylist,
)


class ArchiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "archive"
        self.archive = Archive(self.root)
        self.archive.initialize()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_add_url_is_idempotent_by_source_url(self) -> None:
        first = self.archive.add_url(
            "https://example.com/watch/1",
            "Example",
            playlist="Research",
        )
        second = self.archive.add_url(
            "https://example.com/watch/1",
            "Changed title",
        )

        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.archive.list_items()), 1)
        self.assertEqual(second.title, "Example")

    def test_packaged_archive_root_uses_macos_application_support(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"SECOND_BRAIN_PACKAGED": "1"},
                clear=True,
            ),
            patch("second_brain_archive.archive.platform.system", return_value="Darwin"),
            patch(
                "second_brain_archive.archive.Path.home",
                return_value=Path("/Users/example"),
            ),
        ):
            root = default_archive_root()

        self.assertEqual(
            root,
            Path("/Users/example/Library/Application Support/Second Brain Archive"),
        )

    def test_packaged_archive_root_uses_windows_local_app_data(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "SECOND_BRAIN_PACKAGED": "1",
                    "LOCALAPPDATA": "C:/Users/example/AppData/Local",
                },
                clear=True,
            ),
            patch("second_brain_archive.archive.platform.system", return_value="Windows"),
        ):
            root = default_archive_root()

        self.assertEqual(
            root,
            Path("C:/Users/example/AppData/Local/Second Brain Archive"),
        )

    def test_import_file_copies_media_transcript_and_manifest(self) -> None:
        media = Path(self.temporary_directory.name) / "source.mp4"
        media.write_bytes(b"sample media")
        transcript = Path(self.temporary_directory.name) / "source.srt"
        transcript.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8"
        )

        item = self.archive.import_file(
            media,
            title="My video",
            rights_status="owned",
            transcript=transcript,
        )

        expected_hash = hashlib.sha256(b"sample media").hexdigest()
        self.assertEqual(item.media_sha256, expected_hash)
        self.assertTrue((self.root / item.media_path).is_file())
        self.assertTrue((self.root / item.transcript_path).is_file())

        manifest_path = self.root / "records" / f"{item.id}.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["rights_status"], "owned")
        self.assertEqual(manifest["metadata"]["original_filename"], "source.mp4")

    def test_reference_or_unknown_file_import_is_rejected(self) -> None:
        media = Path(self.temporary_directory.name) / "source.mp4"
        media.write_bytes(b"sample media")

        with self.assertRaises(ValueError):
            self.archive.import_file(
                media,
                title="Unclear rights",
                rights_status="reference",
            )

    def test_same_media_is_stored_once(self) -> None:
        first_source = Path(self.temporary_directory.name) / "first.mp4"
        second_source = Path(self.temporary_directory.name) / "second.mp4"
        first_source.write_bytes(b"same bytes")
        second_source.write_bytes(b"same bytes")

        first = self.archive.import_file(
            first_source,
            title="First record",
            rights_status="owned",
        )
        second = self.archive.import_file(
            second_source,
            title="Second record",
            rights_status="owned",
        )

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.media_path, second.media_path)
        self.assertEqual(len(list((self.root / "media").rglob("*.mp4"))), 1)

    def test_google_authorized_catalog_items_are_deleted_on_disconnect(self) -> None:
        authorized = self.archive.add_url(
            "https://www.youtube.com/watch?v=authorized",
            "Authorized item",
            metadata={"google_authorized_data": True},
        )
        self.archive.add_url(
            "https://example.com/manual",
            "Manual item",
        )
        self.archive.index_segments(
            authorized.id,
            [TranscriptSegment(0, 5, "삭제할 Google 승인 데이터")],
        )

        deleted = self.archive.delete_google_authorized_items()

        self.assertEqual(deleted, 1)
        self.assertIsNone(self.archive.get_item(authorized.id))
        self.assertEqual(len(self.archive.list_items()), 1)
        self.assertEqual(self.archive.search("승인 데이터"), [])

    def test_transcript_chunks_are_searchable_with_timestamps(self) -> None:
        media = Path(self.temporary_directory.name) / "lecture.mp4"
        media.write_bytes(b"media")
        item = self.archive.import_file(
            media, title="공정 강의", rights_status="owned"
        )
        self.archive.index_segments(
            item.id,
            [
                TranscriptSegment(
                    12.5,
                    33.0,
                    "열교환기 효율을 높이려면 온도 차이와 오염 계수를 확인한다.",
                )
            ],
        )

        hits = self.archive.search("열교환기")

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].item_id, item.id)
        self.assertEqual(hits[0].timestamp, "00:00:12")

    def test_natural_language_question_finds_relevant_korean_terms(self) -> None:
        item = self.archive.add_url(
            "https://example.com/watch?v=phone",
            "스마트폰 습관",
        )
        self.archive.index_segments(
            item.id,
            [
                TranscriptSegment(
                    42,
                    55,
                    "스마트폰에서 벗어나는 해결 방법은 의지력보다 환경을 바꾸는 것입니다.",
                )
            ],
        )
        unrelated = self.archive.add_url(
            "https://example.com/watch?v=unrelated-method",
            "관련 없는 해결책",
        )
        self.archive.index_segments(
            unrelated.id,
            [TranscriptSegment(0, 10, "어려운 문제의 이유와 해결 방법을 설명합니다.")],
        )

        hits = self.archive.search(
            "스마트폰에서 헤어나오기 어려운 이유와 해결 방법은 무엇인가요?"
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].item_id, item.id)

    def test_natural_language_search_rejects_single_generic_word_match(self) -> None:
        item = self.archive.add_url(
            "https://example.com/watch?v=unrelated",
            "관련 없는 자료",
        )
        self.archive.index_segments(
            item.id,
            [TranscriptSegment(0, 10, "논문을 읽지 않은 사람의 습관을 설명합니다.")],
        )

        hits = self.archive.search(
            "보관하지 않은 양자역학 논문은 무엇을 주장하나요?"
        )

        self.assertEqual(hits, [])

    def test_specific_question_does_not_use_unrelated_recent_chunks(self) -> None:
        class EmptyArchive:
            def __init__(self) -> None:
                self.recent_chunks_called = False

            def search(self, query: str, limit: int) -> list:
                return []

            def recent_chunks(self, limit: int) -> list:
                self.recent_chunks_called = True
                return []

        archive = EmptyArchive()
        answer = OllamaAssistant(archive).ask("존재하지 않는 특정 주제는 무엇인가요?")

        self.assertEqual(answer.sources, [])
        self.assertFalse(archive.recent_chunks_called)

    def test_download_import_updates_existing_url_and_indexes_subtitle(self) -> None:
        source_url = "https://example.com/watch?v=abc"
        registered = self.archive.add_url(source_url, "Queued")
        staged = Path(self.temporary_directory.name) / "abc"
        staged.mkdir()
        (staged / "abc.mp4").write_bytes(b"downloaded media")
        (staged / "abc.ko.vtt").write_text(
            "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n좋은 콘텐츠를 저장합니다.\n",
            encoding="utf-8",
        )
        (staged / "abc.info.json").write_text(
            json.dumps(
                {
                    "id": "abc",
                    "title": "Downloaded title",
                    "webpage_url": source_url,
                    "extractor_key": "Youtube",
                    "channel": "Creator",
                    "duration": 10,
                }
            ),
            encoding="utf-8",
        )

        item = Downloader(self.archive)._import_download(
            staged / "abc.info.json",
            DownloadOptions(playlist="Saved"),
        )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.id, registered.id)
        self.assertEqual(item.status, "ready")
        self.archive.index_segments(
            item.id,
            make_chunks(parse_subtitle(self.root / item.transcript_path)),
        )
        self.assertEqual(self.archive.search("콘텐츠")[0].item_id, item.id)

    def test_subtitle_only_import_attaches_transcript_without_media(self) -> None:
        source_url = "https://www.youtube.com/watch?v=subtitle-only"
        registered = self.archive.add_url(source_url, "Subtitle only")
        staged = Path(self.temporary_directory.name) / "subtitle-only"
        staged.mkdir()
        (staged / "subtitle-only.ko.vtt").write_text(
            "WEBVTT\n\n00:00:02.000 --> 00:00:05.000\n자막만 저장합니다.\n",
            encoding="utf-8",
        )
        info_path = staged / "subtitle-only.info.json"
        info_path.write_text(
            json.dumps(
                {
                    "id": "subtitle-only",
                    "title": "Subtitle only",
                    "webpage_url": source_url,
                    "extractor_key": "Youtube",
                }
            ),
            encoding="utf-8",
        )

        item = Downloader(self.archive)._import_subtitle_download(
            info_path,
            DownloadOptions(subtitles_only=True),
        )

        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.id, registered.id)
        self.assertIsNone(item.media_path)
        self.assertTrue(item.transcript_path)
        self.assertEqual(self.archive.search("자막만")[0].item_id, item.id)

    def test_subtitle_only_command_skips_media_download(self) -> None:
        with (
            patch(
                "second_brain_archive.downloader.find_executable",
                return_value="yt-dlp",
            ),
            patch(
                "second_brain_archive.downloader.ffmpeg_executable",
                return_value=None,
            ),
            patch(
                "second_brain_archive.downloader.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, ""),
            ) as run,
        ):
            Downloader(self.archive).download(
                "https://www.youtube.com/watch?v=subtitle-only",
                DownloadOptions(subtitles_only=True),
            )

        command = run.call_args.args[0]
        self.assertIn("--skip-download", command)
        self.assertIn("--write-subs", command)
        self.assertNotIn("--format", command)
        self.assertNotIn("--download-archive", command)

    def test_embedded_downloader_uses_bundled_ffmpeg(self) -> None:
        captured: dict = {}

        class FakeYouTubeDL:
            def __init__(self, parameters: dict) -> None:
                captured.update(parameters)

            def __enter__(self):
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def download(self, urls: list[str]) -> int:
                captured["urls"] = urls
                return 0

        with patch("yt_dlp.YoutubeDL", FakeYouTubeDL):
            result = Downloader._run_embedded(
                "https://example.com/watch?v=embedded",
                "/tmp/%(id)s.%(ext)s",
                Path("/tmp/archive.txt"),
                DownloadOptions(),
                "/bundle/ffmpeg",
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(captured["ffmpeg_location"], "/bundle/ffmpeg")
        self.assertEqual(
            captured["urls"],
            ["https://example.com/watch?v=embedded"],
        )

    def test_markdown_export_contains_timestamp_and_source(self) -> None:
        media = Path(self.temporary_directory.name) / "lecture.mp4"
        media.write_bytes(b"media")
        item = self.archive.import_file(
            media,
            title="Export test",
            rights_status="personal-use",
            source_url="https://example.com/watch?v=1",
        )
        self.archive.index_segments(
            item.id, [TranscriptSegment(61, 70, "Important source text")]
        )

        exported = export_item_markdown(self.archive, item)
        text = exported.read_text(encoding="utf-8")

        self.assertIn("00:01:01", text)
        self.assertIn("https://example.com/watch?v=1&t=61s", text)

    def test_collection_export_combines_selected_items(self) -> None:
        first = self.archive.add_url(
            "https://example.com/watch?v=first",
            "First video",
            playlist="Study",
        )
        second = self.archive.add_url(
            "https://example.com/watch?v=second",
            "Second video",
            playlist="Study",
        )
        self.archive.index_segments(
            first.id, [TranscriptSegment(5, 9, "첫 번째 자료 내용")]
        )
        self.archive.index_segments(
            second.id, [TranscriptSegment(12, 18, "두 번째 자료 내용")]
        )

        exported = export_items_markdown(
            self.archive, [first, second], "Study"
        )
        text = exported.read_text(encoding="utf-8")

        self.assertIn("# Study", text)
        self.assertIn("## 1. First video", text)
        self.assertIn("## 2. Second video", text)
        self.assertIn("첫 번째 자료 내용", text)
        self.assertIn(
            "https://example.com/watch?v=second&t=12s",
            text,
        )


class SubtitleTest(unittest.TestCase):
    def test_vtt_parser_removes_tags_and_duplicate_auto_captions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.vtt"
            path.write_text(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:02.000\n<c>첫 문장</c>\n\n"
                "00:00:02.000 --> 00:00:04.000\n첫 문장\n\n"
                "00:00:04.000 --> 00:00:06.000\n둘째 문장\n",
                encoding="utf-8",
            )
            segments = parse_subtitle(path)

        self.assertEqual([segment.text for segment in segments], ["첫 문장", "둘째 문장"])


class YouTubeAccountTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "archive"
        self.account = YouTubeAccount(self.root)
        self.client_source = Path(self.temporary_directory.name) / "client.json"
        self.client_source.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "client-id.apps.googleusercontent.com",
                        "client_secret": "secret",
                    }
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_client_config_and_pkce_authorization_are_stored_securely(self) -> None:
        self.account.install_client_config(self.client_source)
        authorization_url = self.account.authorization_url(
            "http://127.0.0.1:8765/"
        )

        parameters = parse_qs(urlparse(authorization_url).query)
        self.assertEqual(
            parameters["scope"][0],
            "https://www.googleapis.com/auth/youtube.readonly",
        )
        self.assertEqual(parameters["code_challenge_method"][0], "S256")
        self.assertTrue(parameters["state"][0])
        self.assertEqual(os.stat(self.account.client_path).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.account.pending_path).st_mode & 0o777, 0o600)

    def test_environment_oauth_client_removes_json_requirement(self) -> None:
        account = YouTubeAccount(self.root)
        with patch.dict(
            os.environ,
            {
                "SECOND_BRAIN_YOUTUBE_CLIENT_ID": (
                    "release-client.apps.googleusercontent.com"
                ),
                "SECOND_BRAIN_YOUTUBE_CLIENT_SECRET": "release-secret",
            },
            clear=False,
        ):
            authorization_url = account.authorization_url(
                "http://127.0.0.1:8765/"
            )
            self.assertTrue(account.is_configured)
            self.assertEqual(account.configuration_source, "environment")

        parameters = parse_qs(urlparse(authorization_url).query)
        self.assertEqual(
            parameters["client_id"][0],
            "release-client.apps.googleusercontent.com",
        )

    def test_bundled_oauth_client_is_detected(self) -> None:
        account = YouTubeAccount(self.root)
        account.bundled_client_path = self.client_source

        self.assertTrue(account.is_configured)
        self.assertEqual(account.configuration_source, "bundled")

    def test_pkce_token_exchange_does_not_require_client_secret(self) -> None:
        public_client = Path(self.temporary_directory.name) / "public-client.json"
        public_client.write_text(
            json.dumps(
                {
                    "installed": {
                        "client_id": "public-client.apps.googleusercontent.com",
                        "project_id": "public-project",
                    }
                }
            ),
            encoding="utf-8",
        )
        self.account.bundled_client_path = public_client
        self.account._write_secret(
            self.account.pending_path,
            {
                "state": "expected-state",
                "code_verifier": "verifier",
                "redirect_uri": "http://127.0.0.1:8765/",
                "created_at": int(time.time()),
            },
        )

        with patch.object(
            self.account,
            "_post_form",
            return_value={"access_token": "token", "expires_in": 3600},
        ) as post_form:
            self.account.exchange_callback("authorization-code", "expected-state")

        payload = post_form.call_args.args[1]
        self.assertEqual(
            payload["client_id"],
            "public-client.apps.googleusercontent.com",
        )
        self.assertEqual(payload["code_verifier"], "verifier")
        self.assertNotIn("client_secret", payload)

    def test_project_id_is_read_from_oauth_json(self) -> None:
        data = json.loads(self.client_source.read_text(encoding="utf-8"))
        data["installed"]["project_id"] = "second-brain-production"
        self.client_source.write_text(json.dumps(data), encoding="utf-8")
        self.account.install_client_config(self.client_source)

        self.assertEqual(self.account.project_id, "second-brain-production")

    def test_disconnect_revokes_google_token_and_deletes_local_token(self) -> None:
        self.account._write_secret(
            self.account.token_path,
            {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
            },
        )
        with patch(
            "urllib.request.urlopen",
            return_value=JSONResponse({}),
        ) as urlopen:
            revoked = self.account.disconnect()

        request = urlopen.call_args.args[0]
        parameters = parse_qs(request.data.decode("utf-8"))
        self.assertTrue(revoked)
        self.assertEqual(parameters["token"], ["refresh-token"])
        self.assertFalse(self.account.token_path.exists())

    def test_playlist_and_item_pagination_are_normalized(self) -> None:
        account = FakeYouTubeAccount(self.root)
        playlists = account.list_playlists()
        items = account.list_playlist_items("PL1")

        self.assertEqual([playlist.title for playlist in playlists], ["First", "Second"])
        self.assertEqual(playlists[0].privacy_status, "private")
        self.assertEqual(playlists[0].item_count, 2)
        self.assertEqual([item.video_id for item in items], ["video-1", "video-2"])
        self.assertEqual(items[1].position, 1)

    def test_disabled_api_error_exposes_activation_url(self) -> None:
        activation_url = (
            "https://console.developers.google.com/apis/api/"
            "youtube.googleapis.com/overview?project=555924142296"
        )
        payload = {
            "error": {
                "code": 403,
                "message": "YouTube Data API v3 is disabled.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "SERVICE_DISABLED",
                        "metadata": {"activationUrl": activation_url},
                    }
                ],
            }
        }
        response_error = HTTPError(
            "https://www.googleapis.com/youtube/v3/playlists",
            403,
            "Forbidden",
            {},
            io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

        with patch("urllib.request.urlopen", side_effect=response_error):
            with self.assertRaises(YouTubeAPIError) as context:
                self.account._open_json(Request(response_error.url))

        self.assertEqual(context.exception.reason, "SERVICE_DISABLED")
        self.assertEqual(context.exception.activation_url, activation_url)
        self.assertEqual(str(context.exception), "YouTube Data API v3 is disabled.")


class FakeYouTubeAccount(YouTubeAccount):
    def _api_get(self, resource: str, parameters: dict[str, str]) -> dict:
        page = parameters.get("pageToken")
        if resource == "playlists":
            if not page:
                return {
                    "items": [
                        {
                            "id": "PL1",
                            "snippet": {"title": "First", "thumbnails": {}},
                            "contentDetails": {"itemCount": 2},
                            "status": {"privacyStatus": "private"},
                        }
                    ],
                    "nextPageToken": "next",
                }
            return {
                "items": [
                    {
                        "id": "PL2",
                        "snippet": {"title": "Second", "thumbnails": {}},
                        "contentDetails": {"itemCount": 1},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }
        if not page:
            return {
                "items": [
                    {
                        "snippet": {
                            "title": "Video one",
                            "position": 0,
                            "resourceId": {"videoId": "video-1"},
                            "thumbnails": {},
                        },
                        "contentDetails": {"videoId": "video-1"},
                    }
                ],
                "nextPageToken": "next",
            }
        return {
            "items": [
                {
                    "snippet": {
                        "title": "Video two",
                        "position": 1,
                        "resourceId": {"videoId": "video-2"},
                        "thumbnails": {},
                    },
                    "contentDetails": {"videoId": "video-2"},
                }
            ]
        }


class JSONResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> JSONResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class OllamaRuntimeTest(unittest.TestCase):
    def test_status_lists_installed_models(self) -> None:
        payload = {
            "models": [
                {"name": "llama3.1:8b"},
                {"name": DEFAULT_OLLAMA_MODEL},
            ]
        }
        with patch("urllib.request.urlopen", return_value=JSONResponse(payload)):
            status = OllamaRuntime().status()

        self.assertTrue(status.running)
        self.assertTrue(status.ready)
        self.assertEqual(
            status.models,
            (DEFAULT_OLLAMA_MODEL, "llama3.1:8b"),
        )

    def test_pull_model_uses_ollama_api(self) -> None:
        with patch(
            "urllib.request.urlopen",
            side_effect=[
                JSONResponse({"models": []}),
                JSONResponse({"status": "success"}),
            ],
        ) as urlopen:
            message = OllamaRuntime().pull_model(DEFAULT_OLLAMA_MODEL)

        request = urlopen.call_args_list[1].args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], DEFAULT_OLLAMA_MODEL)
        self.assertFalse(payload["stream"])
        self.assertIn("완료", message)

    def test_choose_model_prefers_recommended_installed_model(self) -> None:
        selected = OllamaRuntime.choose_model(
            ("llama3.1:8b", DEFAULT_OLLAMA_MODEL),
            preferred="missing:latest",
        )

        self.assertEqual(selected, DEFAULT_OLLAMA_MODEL)

    def test_windows_default_ollama_install_is_detected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("second_brain_archive.local_ai.platform.system", return_value="Windows"),
            patch("second_brain_archive.local_ai.shutil.which", return_value=None),
            patch.dict(os.environ, {"LOCALAPPDATA": directory}, clear=False),
        ):
            executable = Path(directory) / "Programs" / "Ollama" / "ollama.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"")

            detected = OllamaRuntime._command_path()

        self.assertEqual(detected, str(executable))


class DistributionTest(unittest.TestCase):
    def test_development_profile_can_be_selected_with_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"SECOND_BRAIN_PROFILE": "public"},
            clear=False,
        ):
            self.assertEqual(distribution_profile(), "public")

    def test_public_capture_panel_has_no_url_download_form(self) -> None:
        panel = _capture_panel(True)

        self.assertNotIn('action="/download"', panel)
        self.assertIn("링크와 메타데이터만", panel)
        self.assertIn('action="/import"', panel)

    def test_public_playlist_card_only_offers_catalog_import(self) -> None:
        card = _youtube_playlist_card(
            YouTubePlaylist(
                id="PL1",
                title="Playlist",
                description="",
                privacy_status="private",
                item_count=2,
                thumbnail_url=None,
            ),
            allow_downloads=False,
        )

        self.assertIn('value="catalog"', card)
        self.assertNotIn('value="download"', card)
        self.assertNotIn('value="subtitles"', card)

    def test_public_info_uses_environment_and_derives_policy_urls(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SECOND_BRAIN_OPERATOR_NAME": "Archive Operator",
                "SECOND_BRAIN_SUPPORT_EMAIL": "support@example.com",
                "SECOND_BRAIN_HOMEPAGE_URL": "https://example.com/archive",
            },
            clear=False,
        ):
            info = public_info()

        self.assertEqual(info.operator_name, "Archive Operator")
        self.assertEqual(info.privacy_url, "https://example.com/archive/privacy/")
        self.assertEqual(info.terms_url, "https://example.com/archive/terms/")
        self.assertEqual(info.validation_errors(), [])

    def test_policy_pages_show_release_contact(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SECOND_BRAIN_OPERATOR_NAME": "Archive Operator",
                "SECOND_BRAIN_SUPPORT_EMAIL": "support@example.com",
            },
            clear=False,
        ):
            privacy = _privacy_content()
            terms = _terms_content()

        self.assertIn("Archive Operator", privacy)
        self.assertIn("mailto:support@example.com", privacy)
        self.assertIn("Archive Operator", terms)

    def test_public_site_links_all_installers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "site"
            subprocess.run(
                [
                    sys.executable,
                    "scripts/build_public_site.py",
                    str(output),
                ],
                cwd=Path(__file__).resolve().parents[1],
                check=True,
                capture_output=True,
                text=True,
            )
            homepage = (output / "index.html").read_text(encoding="utf-8")
            verification = (
                output / "google139ae45559051ca9.html"
            ).read_text(encoding="utf-8")

        self.assertIn("Second-Brain-Archive-macOS-arm64.dmg", homepage)
        self.assertIn("Second-Brain-Archive-macOS-x86_64.dmg", homepage)
        self.assertIn("Second-Brain-Archive-Windows-x64.exe", homepage)
        self.assertIn("개발자 서명 전 시험 배포본", homepage)
        self.assertEqual(
            verification,
            "google-site-verification: google139ae45559051ca9.html\n",
        )


if __name__ == "__main__":
    unittest.main()
