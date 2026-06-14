from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


YOUTUBE_READONLY_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


class YouTubeAPIError(RuntimeError):
    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        reason: str | None = None,
        activation_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.activation_url = activation_url


@dataclass(frozen=True)
class YouTubePlaylist:
    id: str
    title: str
    description: str
    privacy_status: str
    item_count: int
    thumbnail_url: str | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.id}"


@dataclass(frozen=True)
class YouTubePlaylistItem:
    video_id: str
    title: str
    creator: str | None
    position: int
    published_at: str | None
    thumbnail_url: str | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


class YouTubeAccount:
    def __init__(self, archive_root: Path | str) -> None:
        self.root = Path(archive_root).expanduser().resolve()
        self.secrets_directory = self.root / "secrets"
        self.client_path = self.secrets_directory / "youtube_client.json"
        private_bundle = Path(__file__).with_name("youtube_oauth.json")
        public_bundle = Path(__file__).with_name("youtube_oauth_public.json")
        self.bundled_client_path = (
            private_bundle if private_bundle.is_file() else public_bundle
        )
        self.token_path = self.secrets_directory / "youtube_token.json"
        self.pending_path = self.secrets_directory / "youtube_oauth_pending.json"

    @property
    def is_configured(self) -> bool:
        try:
            self._load_client()
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            return False
        return True

    @property
    def configuration_source(self) -> str:
        if self.client_path.is_file():
            return "local"
        if os.environ.get("SECOND_BRAIN_YOUTUBE_CLIENT_ID"):
            return "environment"
        if self.bundled_client_path.is_file():
            return "bundled"
        return "missing"

    @property
    def is_connected(self) -> bool:
        return self.token_path.is_file()

    @property
    def project_id(self) -> str | None:
        try:
            return self._load_client().get("project_id") or None
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            return None

    def install_client_config(self, source: Path | str) -> None:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"OAuth JSON을 찾을 수 없습니다: {source_path}")
        data = json.loads(source_path.read_text(encoding="utf-8"))
        self._client_from_data(data)
        self.secrets_directory.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, self.client_path)
        os.chmod(self.client_path, 0o600)

    def authorization_url(self, redirect_uri: str) -> str:
        client = self._load_client()
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        pending = {
            "state": state,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "created_at": int(time.time()),
        }
        self._write_secret(self.pending_path, pending)
        query = urllib.parse.urlencode(
            {
                "client_id": client["client_id"],
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": YOUTUBE_READONLY_SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{AUTHORIZATION_ENDPOINT}?{query}"

    def exchange_callback(self, code: str, state: str) -> None:
        pending = self._read_json(self.pending_path)
        if not pending or not secrets.compare_digest(
            str(pending.get("state", "")), state
        ):
            raise ValueError("OAuth state가 일치하지 않습니다. 연결을 다시 시작하세요.")
        if int(time.time()) - int(pending.get("created_at", 0)) > 900:
            raise ValueError("OAuth 연결 요청이 만료되었습니다. 다시 시작하세요.")
        client = self._load_client()
        payload = {
            "client_id": client["client_id"],
            "code": code,
            "code_verifier": pending["code_verifier"],
            "grant_type": "authorization_code",
            "redirect_uri": pending["redirect_uri"],
        }
        if client.get("client_secret"):
            payload["client_secret"] = client["client_secret"]
        response = self._post_form(TOKEN_ENDPOINT, payload)
        self._store_token(response, previous=None)
        self.pending_path.unlink(missing_ok=True)

    def disconnect(self) -> bool:
        token = self._read_json(self.token_path)
        revoked = False
        if token:
            value = token.get("refresh_token") or token.get("access_token")
            if value:
                request = urllib.request.Request(
                    REVOCATION_ENDPOINT,
                    data=urllib.parse.urlencode({"token": str(value)}).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(request, timeout=30):
                        revoked = True
                except (OSError, urllib.error.URLError):
                    revoked = False
        self.token_path.unlink(missing_ok=True)
        self.pending_path.unlink(missing_ok=True)
        return revoked

    def list_playlists(self) -> list[YouTubePlaylist]:
        playlists: list[YouTubePlaylist] = []
        page_token: str | None = None
        while True:
            parameters = {
                "part": "snippet,contentDetails,status",
                "mine": "true",
                "maxResults": "50",
            }
            if page_token:
                parameters["pageToken"] = page_token
            data = self._api_get("playlists", parameters)
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                details = item.get("contentDetails", {})
                status = item.get("status", {})
                playlists.append(
                    YouTubePlaylist(
                        id=item["id"],
                        title=snippet.get("title") or item["id"],
                        description=snippet.get("description", ""),
                        privacy_status=status.get("privacyStatus", "unknown"),
                        item_count=int(details.get("itemCount", 0)),
                        thumbnail_url=_best_thumbnail(snippet.get("thumbnails", {})),
                    )
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return playlists

    def list_playlist_items(self, playlist_id: str) -> list[YouTubePlaylistItem]:
        items: list[YouTubePlaylistItem] = []
        page_token: str | None = None
        while True:
            parameters = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": "50",
            }
            if page_token:
                parameters["pageToken"] = page_token
            data = self._api_get("playlistItems", parameters)
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                details = item.get("contentDetails", {})
                resource = snippet.get("resourceId", {})
                video_id = details.get("videoId") or resource.get("videoId")
                if not video_id:
                    continue
                items.append(
                    YouTubePlaylistItem(
                        video_id=video_id,
                        title=snippet.get("title") or video_id,
                        creator=snippet.get("videoOwnerChannelTitle"),
                        position=int(snippet.get("position", len(items))),
                        published_at=details.get("videoPublishedAt"),
                        thumbnail_url=_best_thumbnail(snippet.get("thumbnails", {})),
                    )
                )
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def _api_get(self, resource: str, parameters: dict[str, str]) -> dict[str, Any]:
        token = self._valid_access_token()
        url = f"{YOUTUBE_API}/{resource}?{urllib.parse.urlencode(parameters)}"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        return self._open_json(request)

    def _valid_access_token(self) -> str:
        token = self._read_json(self.token_path)
        if not token:
            raise RuntimeError("YouTube 계정이 연결되지 않았습니다.")
        if int(token.get("expires_at", 0)) > int(time.time()) + 60:
            return str(token["access_token"])
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("YouTube 토큰이 만료되었습니다. 계정을 다시 연결하세요.")
        client = self._load_client()
        payload = {
            "client_id": client["client_id"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        if client.get("client_secret"):
            payload["client_secret"] = client["client_secret"]
        response = self._post_form(TOKEN_ENDPOINT, payload)
        self._store_token(response, previous=token)
        return str(response["access_token"])

    def _load_client(self) -> dict[str, str]:
        if self.client_path.is_file():
            return self._client_from_data(
                json.loads(self.client_path.read_text(encoding="utf-8"))
            )
        environment_client_id = os.environ.get(
            "SECOND_BRAIN_YOUTUBE_CLIENT_ID", ""
        ).strip()
        if environment_client_id:
            return {
                "client_id": environment_client_id,
                "client_secret": os.environ.get(
                    "SECOND_BRAIN_YOUTUBE_CLIENT_SECRET", ""
                ).strip(),
                "project_id": os.environ.get(
                    "SECOND_BRAIN_GOOGLE_CLOUD_PROJECT", ""
                ).strip(),
            }
        if self.bundled_client_path.is_file():
            return self._client_from_data(
                json.loads(self.bundled_client_path.read_text(encoding="utf-8"))
            )
        raise RuntimeError(
            "이 배포본에 Google OAuth 설정이 포함되지 않았습니다. "
            "앱 제작자가 배포용 OAuth 클라이언트를 먼저 설정해야 합니다."
        )

    @staticmethod
    def _client_from_data(data: dict[str, Any]) -> dict[str, str]:
        client = data.get("installed") or data.get("web")
        if not isinstance(client, dict) or not client.get("client_id"):
            raise ValueError("Google OAuth 클라이언트 JSON 형식이 아닙니다.")
        return {
            "client_id": str(client["client_id"]),
            "client_secret": str(client.get("client_secret", "")),
            "project_id": str(
                client.get("project_id") or data.get("project_id", "")
            ),
        }

    def _store_token(
        self, response: dict[str, Any], previous: dict[str, Any] | None
    ) -> None:
        token = dict(previous or {})
        token.update(response)
        token["expires_at"] = int(time.time()) + int(response.get("expires_in", 3600))
        if not response.get("refresh_token") and previous:
            token["refresh_token"] = previous.get("refresh_token")
        self._write_secret(self.token_path, token)

    def _write_secret(self, path: Path, data: dict[str, Any]) -> None:
        self.secrets_directory.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(path, 0o600)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            method="POST",
        )
        return YouTubeAccount._open_json(request)

    @staticmethod
    def _open_json(request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            message = f"YouTube API가 HTTP {error.code}을 반환했습니다."
            reason = None
            activation_url = None
            try:
                payload = json.loads(detail)
                api_error = payload.get("error", {})
                message = str(api_error.get("message") or message)
                for item in api_error.get("details", []):
                    if not isinstance(item, dict):
                        continue
                    if item.get("@type") == "type.googleapis.com/google.rpc.ErrorInfo":
                        reason = item.get("reason")
                        metadata = item.get("metadata", {})
                        if isinstance(metadata, dict):
                            activation_url = metadata.get("activationUrl")
                    if not activation_url:
                        for link in item.get("links", []):
                            if isinstance(link, dict) and link.get("url"):
                                activation_url = link["url"]
                                break
            except (json.JSONDecodeError, AttributeError, TypeError):
                if detail:
                    message = detail
            raise YouTubeAPIError(
                error.code,
                message,
                reason=reason,
                activation_url=activation_url,
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"YouTube API에 연결할 수 없습니다: {error}") from error


def _best_thumbnail(thumbnails: dict[str, Any]) -> str | None:
    for name in ("maxres", "standard", "high", "medium", "default"):
        value = thumbnails.get(name)
        if isinstance(value, dict) and value.get("url"):
            return str(value["url"])
    return None
