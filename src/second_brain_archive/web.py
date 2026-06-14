from __future__ import annotations

import html
import json
import mimetypes
import threading
import traceback
import uuid
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlparse

from .ai import OllamaAssistant
from .archive import Archive, ArchiveItem
from .downloader import DownloadOptions, Downloader
from .distribution import is_public_distribution
from .exporter import (
    export_answer_markdown,
    export_item_markdown,
    export_items_markdown,
)
from .local_ai import (
    DEFAULT_OLLAMA_MODEL,
    OLLAMA_DOWNLOAD_URL,
    LocalAIStatus,
    OllamaRuntime,
)
from .public_info import public_info
from .subtitles import make_chunks, parse_subtitle
from .transcriber import Transcriber
from .youtube import YouTubeAccount, YouTubeAPIError, YouTubePlaylist


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def start(self, label: str, task: Callable[[], str]) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {"status": "running", "label": label, "message": ""}

        def run() -> None:
            try:
                message = task()
                state = {"status": "done", "label": label, "message": message}
            except Exception as error:  # noqa: BLE001 - exposed as a local job result
                state = {
                    "status": "error",
                    "label": label,
                    "message": str(error),
                    "traceback": traceback.format_exc(),
                }
            with self._lock:
                self._jobs[job_id] = state

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


class Application:
    def __init__(
        self,
        archive: Archive,
        ollama_model: str = DEFAULT_OLLAMA_MODEL,
        oauth_redirect_uri: str = "http://127.0.0.1:8765/",
    ) -> None:
        self.archive = archive
        self.archive.initialize()
        self.downloader = Downloader(archive)
        self.transcriber = Transcriber(archive)
        self.assistant = OllamaAssistant(archive, model=ollama_model)
        self.ollama_model = ollama_model
        self.local_ai = OllamaRuntime()
        self.youtube = YouTubeAccount(archive.root)
        self.public_distribution = is_public_distribution()
        self.oauth_redirect_uri = oauth_redirect_uri
        self.jobs = JobStore()


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def serve(
    archive: Archive,
    host: str = "127.0.0.1",
    port: int = 8765,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
) -> None:
    application = Application(
        archive,
        ollama_model=ollama_model,
        oauth_redirect_uri=f"http://127.0.0.1:{port}/",
    )

    class Handler(ArchiveRequestHandler):
        app = application

    server = LocalThreadingHTTPServer((host, port), Handler)
    print(f"Second Brain Archive: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


class ArchiveRequestHandler(BaseHTTPRequestHandler):
    app: Application
    server_version = "SecondBrainArchive/0.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/" and (_first(query, "code") or _first(query, "error")):
            self._youtube_callback(query)
        elif parsed.path == "/":
            self._home(query)
        elif parsed.path == "/search":
            self._search(query)
        elif parsed.path == "/item":
            self._item(query)
        elif parsed.path == "/exports":
            self._exports()
        elif parsed.path == "/youtube":
            self._youtube(query)
        elif parsed.path == "/setup":
            self._setup(query)
        elif parsed.path == "/privacy":
            self._privacy()
        elif parsed.path == "/terms":
            self._terms()
        elif parsed.path == "/api/job":
            self._job(query)
        elif parsed.path == "/asset":
            self._asset(query)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        data = self._form_data()
        if parsed.path == "/download":
            self._download(data)
        elif parsed.path == "/import":
            self._import(data)
        elif parsed.path == "/ask":
            self._ask(data)
        elif parsed.path == "/transcribe":
            self._transcribe(data)
        elif parsed.path == "/export":
            self._export(data)
        elif parsed.path == "/youtube/connect":
            self._youtube_connect(data)
        elif parsed.path == "/youtube/detect":
            self._youtube_detect()
        elif parsed.path == "/youtube/disconnect":
            self._youtube_disconnect()
        elif parsed.path == "/youtube/import":
            self._youtube_import(data)
        elif parsed.path == "/ai/start":
            self._ai_start()
        elif parsed.path == "/ai/pull":
            self._ai_pull(data)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def _home(self, query: dict[str, list[str]]) -> None:
        stats = self.app.archive.stats()
        items = self.app.archive.list_items()[:30]
        ai_status = self.app.local_ai.status()
        job_id = _first(query, "job")
        cards = "".join(_item_card(item) for item in items)
        capture_panel = _capture_panel(self.app.public_distribution)
        job_panel = (
            f"""
            <section class="job" id="job" data-job="{html.escape(job_id)}">
              <strong>작업을 시작했습니다.</strong>
              <span id="job-message">다운로드 또는 전사를 진행하고 있습니다.</span>
            </section>
            """
            if job_id
            else ""
        )
        content = f"""
        <header class="hero">
          <div>
            <p class="eyebrow">LOCAL KNOWLEDGE ARCHIVE</p>
            <h1>좋은 콘텐츠를<br><span>내 지식으로 남기세요.</span></h1>
            <p class="lede">영상, 자막, 메타데이터를 로컬에 보관하고 저장된 근거만으로 검색하고 질문합니다.</p>
          </div>
          <div class="stats">
            {_stat("자료", stats["items"])}
            {_stat("원본", stats["media"])}
            {_stat("자막", stats["transcripts"])}
            {_stat("검색 조각", stats["chunks"])}
          </div>
        </header>
        {job_panel}
        <section class="account-strip">
          <div>
            <p class="eyebrow">YOUTUBE ACCOUNT</p>
            <strong>{'계정 연결됨' if self.app.youtube.is_connected else '계정 재생목록 가져오기'}</strong>
            <span>{'내 재생목록을 선택해 아카이브할 수 있습니다.' if self.app.youtube.is_connected else '공식 읽기 전용 OAuth로 내 재생목록을 불러옵니다.'}</span>
          </div>
          <a href="/youtube">{'재생목록 보기' if self.app.youtube.is_connected else 'YouTube 연결'}</a>
        </section>
        <section class="account-strip ai-strip">
          <div>
            <p class="eyebrow">LOCAL AI</p>
            <strong>{_ai_status_title(ai_status)}</strong>
            <span>{_ai_status_message(ai_status)}</span>
          </div>
          <a href="/setup">{'AI 설정 보기' if ai_status.ready else 'AI 준비하기'}</a>
        </section>
        <section class="workspace">
          {capture_panel}
          <article class="panel search-panel">
            <div class="panel-title"><span>02</span><h2>아카이브 탐색</h2></div>
            <form method="get" action="/search">
              <label>내용 검색</label>
              <input name="q" placeholder="영상에서 기억나는 단어나 문장" required>
              <button type="submit" class="secondary">타임스탬프 검색</button>
            </form>
            {_ai_question_form(ai_status, self.app.ollama_model)}
          </article>
        </section>
        <section class="library">
          <div class="section-heading">
            <div><p class="eyebrow">LIBRARY</p><h2>최근 아카이브</h2></div>
            <div class="section-actions">
              <span>{len(items)}개 표시</span>
              <a href="/exports">여러 자료 Markdown 내보내기</a>
            </div>
          </div>
          <div class="grid">{cards or _empty_state()}</div>
        </section>
        """
        self._html("Second Brain Archive", content, job_id=job_id)

    def _setup(self, query: dict[str, list[str]]) -> None:
        ai_status = self.app.local_ai.status()
        job_id = _first(query, "job")
        job_panel = (
            f"""
            <section class="job" id="job" data-job="{html.escape(job_id)}">
              <strong>로컬 AI를 준비하고 있습니다.</strong>
              <span id="job-message">Ollama 실행 또는 모델 다운로드를 진행합니다.</span>
            </section>
            """
            if job_id
            else ""
        )
        youtube_source = self.app.youtube.configuration_source
        if self.app.youtube.is_connected:
            youtube_action = """
            <p class="ready-note">Google 계정과 YouTube 읽기 권한이 연결됐습니다.</p>
            <a class="action-link" href="/youtube">내 재생목록 보기</a>
            """
        elif self.app.youtube.is_configured:
            policy_agreement = (
                """
                <label class="check policy-check">
                  <input type="checkbox" name="policy_accepted" required>
                  <span><a href="/privacy" target="_blank">개인정보처리방침</a>과 <a href="/terms" target="_blank">이용약관</a>에 동의합니다.</span>
                </label>
                """
                if self.app.public_distribution
                else ""
            )
            youtube_action = f"""
            <p>Google 계정을 선택하고 YouTube 읽기 권한을 한 번 승인하면 됩니다.</p>
            <form method="post" action="/youtube/connect">
              {policy_agreement}
              <button>Google 계정으로 YouTube 연결</button>
            </form>
            """
        else:
            youtube_action = """
            <p class="warning-note">현재 개발 빌드에는 공용 Google OAuth 설정이 포함되지 않았습니다.</p>
            <p>배포본에는 앱 제작자의 검증된 OAuth 클라이언트가 포함되므로 일반 사용자는 이 단계를 보지 않습니다.</p>
            """

        installed_models = "".join(
            f"<li><strong>{html.escape(self.app.local_ai.label(model))}</strong>"
            f"<span>{html.escape(model)}</span></li>"
            for model in ai_status.models
        )
        if not ai_status.installed:
            ai_action = f"""
            <p>Ollama를 한 번 설치하면 모든 질문과 답변이 이 컴퓨터 안에서 처리됩니다.</p>
            <a class="oauth-link" href="{OLLAMA_DOWNLOAD_URL}" target="_blank">Ollama 공식 설치 파일 받기 ↗</a>
            <p class="muted">설치 후 Ollama를 실행하고 이 페이지를 새로고침하세요.</p>
            """
        elif not ai_status.running:
            ai_action = """
            <p>Ollama는 설치되어 있지만 실행 중이 아닙니다.</p>
            <form method="post" action="/ai/start">
              <button>Ollama 실행</button>
            </form>
            """
        else:
            recommended_ready = DEFAULT_OLLAMA_MODEL in ai_status.models
            pull_action = (
                '<p class="ready-note">권장 로컬 모델이 준비됐습니다.</p>'
                if recommended_ready
                else f"""
                <form method="post" action="/ai/pull">
                  <input type="hidden" name="model" value="{DEFAULT_OLLAMA_MODEL}">
                  <button>권장 AI 모델 다운로드 · 약 3.3GB</button>
                </form>
                """
            )
            ai_action = f"""
            <p>Ollama가 실행 중입니다. 설치된 모델은 질문 화면에 자동으로 표시됩니다.</p>
            {pull_action}
            <ul class="model-list">{installed_models or '<li>설치된 모델이 없습니다.</li>'}</ul>
            """

        content = f"""
        {_back_link()}
        <section class="page-head">
          <p class="eyebrow">FIRST RUN</p>
          <h1>두 번의 클릭으로 준비합니다.</h1>
          <p>Google은 재생목록을 읽는 데 사용하고, 로컬 AI는 저장한 자막을 이 컴퓨터 안에서 분석합니다.</p>
        </section>
        {job_panel}
        <section class="setup-grid">
          <article class="setup-card">
            <span class="step-number">01</span>
            <p class="eyebrow">GOOGLE ACCOUNT</p>
            <h2>{'연결 완료' if self.app.youtube.is_connected else 'YouTube 재생목록 연결'}</h2>
            {youtube_action}
            <details class="developer-settings">
              <summary>개발자용 OAuth 설정</summary>
              <p class="muted">설정 소스: {html.escape(youtube_source)}</p>
              <form method="post" action="/youtube/detect">
                <button class="secondary">Downloads에서 OAuth JSON 자동 찾기</button>
              </form>
              <form method="post" action="/youtube/connect">
                <label>OAuth 클라이언트 JSON 경로</label>
                <input name="credentials_path" placeholder="/Users/me/Downloads/client_secret_....json" required>
                <button class="secondary">개인 OAuth JSON 사용</button>
              </form>
            </details>
          </article>
          <article class="setup-card">
            <span class="step-number">02</span>
            <p class="eyebrow">LOCAL AI</p>
            <h2>{_ai_status_title(ai_status)}</h2>
            {ai_action}
          </article>
        </section>
        """
        self._html(
            "초기 설정",
            content,
            job_id=job_id,
            job_return_to="/setup",
        )

    def _youtube(self, query: dict[str, list[str]]) -> None:
        if not self.app.youtube.is_configured:
            self._redirect("/setup")
            return

        if not self.app.youtube.is_connected:
            content = f"""
            {_back_link()}
            <section class="page-head">
              <p class="eyebrow">YOUTUBE OAUTH</p>
              <h1>로그인을 완료하세요.</h1>
              <p>OAuth 설정은 준비됐습니다. Google 로그인 창에서 읽기 권한을 승인하세요.</p>
            </section>
            <form method="post" action="/youtube/connect">
              <button>YouTube 로그인 다시 열기</button>
            </form>
            """
            self._html("YouTube 로그인", content)
            return

        api_error: YouTubeAPIError | None = None
        error_message = ""
        playlists: list[YouTubePlaylist] = []
        try:
            playlists = self.app.youtube.list_playlists()
        except YouTubeAPIError as error:
            api_error = error
        except Exception as error:  # noqa: BLE001 - rendered locally
            error_message = str(error)
        playlist_cards = "".join(
            _youtube_playlist_card(
                item,
                allow_downloads=not self.app.public_distribution,
            )
            for item in playlists
        )
        connected = _first(query, "connected")
        if connected and (api_error or error_message):
            notice = '<div class="job done"><strong>계정 인증 완료</strong><span>Google 로그인과 읽기 권한 승인은 정상적으로 끝났습니다.</span></div>'
        elif connected:
            notice = '<div class="job done"><strong>연결 완료</strong><span>내 YouTube 재생목록을 불러왔습니다.</span></div>'
        else:
            notice = ""
        error_panel = _youtube_error_panel(api_error, error_message)
        empty_message = (
            _empty_state(
                "API를 활성화한 뒤 이 페이지에서 다시 불러오세요.",
                title="재생목록을 아직 불러오지 못했습니다.",
            )
            if api_error
            else _empty_state("계정에서 만든 재생목록이 없습니다.")
        )
        content = f"""
        {_back_link()}
        <section class="page-head youtube-head">
          <div><p class="eyebrow">YOUTUBE ACCOUNT</p><h1>내 재생목록</h1>
          <p>재생목록 항목을 먼저 카탈로그에 등록하고, 원하는 경우 영상과 자막까지 저장합니다.</p></div>
          <form method="post" action="/youtube/disconnect"><button class="secondary">계정 연결 해제</button></form>
        </section>
        {notice}
        {error_panel}
        <section class="playlist-grid">
          {playlist_cards or empty_message}
        </section>
        <section class="oauth-note">
          <strong>비공개 자료 처리 범위</strong>
          <p>비공개 재생목록의 제목과 항목은 읽을 수 있습니다. 다만 YouTube Data API는 비공개 영상 원본 파일을 제공하지 않으므로, 소유자 전용 비공개 영상은 목록과 메타데이터만 저장됩니다.</p>
        </section>
        """
        self._html("내 YouTube 재생목록", content)

    def _youtube_detect(self) -> None:
        downloads = Path.home() / "Downloads"
        candidates: list[Path] = []
        for pattern in ("client_secret*.json", "*oauth*.json"):
            candidates.extend(downloads.glob(pattern))
        valid: list[Path] = []
        for candidate in candidates:
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                client = data.get("installed") or data.get("web")
                if isinstance(client, dict) and client.get("client_id"):
                    valid.append(candidate)
            except (OSError, json.JSONDecodeError):
                continue
        if not valid:
            self._message_page(
                "OAuth JSON을 찾지 못했습니다.",
                "Google Cloud에서 데스크톱 앱 OAuth JSON을 다운로드한 뒤 다시 눌러주세요.",
                is_error=True,
            )
            return
        newest = max(valid, key=lambda path: path.stat().st_mtime)
        try:
            self.app.youtube.install_client_config(newest)
            authorization_url = self.app.youtube.authorization_url(
                self.app.oauth_redirect_uri
            )
            webbrowser.open(authorization_url)
        except Exception as error:  # noqa: BLE001 - rendered locally
            self._message_page("YouTube 연결 실패", str(error), is_error=True)
            return
        self._message_page(
            "OAuth JSON을 등록했습니다.",
            f"{newest.name}을 등록하고 Google 로그인 창을 열었습니다.",
        )

    def _search(self, query: dict[str, list[str]]) -> None:
        value = _first(query, "q")
        hits = self.app.archive.search(value)
        results = "".join(
            f"""
            <article class="result">
              <div class="timestamp">{html.escape(hit.timestamp)}</div>
              <div>
                <h3><a href="/item?id={quote(hit.item_id)}">{html.escape(hit.title)}</a></h3>
                <p>{html.escape(hit.text)}</p>
                {_source_link(hit.timestamp_url, "원본 시점 열기")}
              </div>
            </article>
            """
            for hit in hits
        )
        content = f"""
        {_back_link()}
        <section class="page-head"><p class="eyebrow">SEARCH</p>
          <h1>“{html.escape(value)}” 검색 결과</h1><p>{len(hits)}개의 근거 구간을 찾았습니다.</p>
        </section>
        <form class="inline-search" method="get" action="/search">
          <input name="q" value="{html.escape(value)}" required><button>다시 검색</button>
        </form>
        <section class="results">{results or _empty_state("검색 결과가 없습니다.")}</section>
        """
        self._html("검색", content)

    def _item(self, query: dict[str, list[str]]) -> None:
        item_id = _first(query, "id")
        item = self.app.archive.get_item(item_id)
        if item is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        chunks = self.app.archive.chunks_for_item(item.id)
        transcript = "".join(
            f"""
            <article class="transcript-row">
              <a href="{html.escape(_timestamp_url(item.source_url, chunk.start_seconds) or '#')}"
                 target="_blank">{_format_seconds(chunk.start_seconds)}</a>
              <p>{html.escape(chunk.text)}</p>
            </article>
            """
            for chunk in chunks
        )
        media = (
            f'<video controls preload="metadata" src="/asset?path={quote(item.media_path)}"></video>'
            if item.media_path
            else ""
        )
        thumbnail = (
            f'<img class="detail-cover" src="/asset?path={quote(item.thumbnail_path)}" alt="">'
            if item.thumbnail_path
            else ""
        )
        content = f"""
        {_back_link()}
        <section class="detail-head">
          <div>{thumbnail}</div>
          <div>
            <p class="eyebrow">{html.escape(item.platform or "LOCAL")}</p>
            <h1>{html.escape(item.title)}</h1>
            <p>{html.escape(item.creator or "")}</p>
            <div class="badges"><span>{html.escape(item.status)}</span><span>{html.escape(item.rights_status)}</span></div>
            {_source_link(item.source_url, "원본 열기")}
            <div class="actions">
              <form method="post" action="/export"><input type="hidden" name="item_id" value="{item.id}"><button>Markdown 내보내기</button></form>
              {_playlist_export_form(item)}
              <a class="action-link" href="/exports">여러 영상 선택</a>
              {_transcribe_form(item)}
            </div>
          </div>
        </section>
        {media}
        <section class="transcript">
          <div class="section-heading"><div><p class="eyebrow">TRANSCRIPT</p><h2>시간별 내용</h2></div><span>{len(chunks)}개 구간</span></div>
          {transcript or _empty_state("자막이 없습니다. 로컬 전사를 실행하세요.")}
        </section>
        """
        self._html(item.title, content)

    def _exports(self) -> None:
        items = self.app.archive.list_items()
        playlists: dict[str, list[ArchiveItem]] = {}
        for item in items:
            if item.playlist:
                playlists.setdefault(item.playlist, []).append(item)
        playlist_cards = "".join(
            _playlist_export_card(name, playlist_items)
            for name, playlist_items in sorted(playlists.items())
        )
        item_rows = "".join(_export_item_row(item) for item in items)
        content = f"""
        {_back_link()}
        <section class="page-head">
          <p class="eyebrow">MARKDOWN EXPORT</p>
          <h1>여러 자료 내보내기</h1>
          <p>재생목록 전체 또는 체크한 영상들을 하나의 Markdown 문서로 합칩니다.</p>
        </section>
        <section class="export-playlists">
          <div class="section-heading"><div><p class="eyebrow">PLAYLISTS</p><h2>재생목록 단위</h2></div><span>{len(playlists)}개</span></div>
          <div class="export-playlist-grid">{playlist_cards or _empty_state("재생목록이 없습니다.")}</div>
        </section>
        <section class="export-selection">
          <div class="section-heading"><div><p class="eyebrow">CUSTOM SELECTION</p><h2>영상 직접 선택</h2></div><span>{len(items)}개 자료</span></div>
          <form method="post" action="/export" id="batch-export">
            <div class="export-toolbar">
              <label class="check"><input type="checkbox" id="select-all"> 전체 선택</label>
              <span id="selected-count">0개 선택</span>
              <input name="collection_title" placeholder="문서 제목 (선택 사항)">
              <button>선택한 자료를 하나의 Markdown으로 내보내기</button>
            </div>
            <div class="export-rows">{item_rows or _empty_state()}</div>
          </form>
        </section>
        <script>
        const selectAll = document.querySelector('#select-all');
        const itemChecks = [...document.querySelectorAll('.export-row input[type="checkbox"]')];
        const selectedCount = document.querySelector('#selected-count');
        function updateSelectedCount() {{
          const count = itemChecks.filter(input => input.checked).length;
          selectedCount.textContent = count + '개 선택';
          selectAll.checked = count > 0 && count === itemChecks.length;
          selectAll.indeterminate = count > 0 && count < itemChecks.length;
        }}
        selectAll.addEventListener('change', () => {{
          itemChecks.forEach(input => input.checked = selectAll.checked);
          updateSelectedCount();
        }});
        itemChecks.forEach(input => input.addEventListener('change', updateSelectedCount));
        document.querySelector('#batch-export').addEventListener('submit', event => {{
          if (!itemChecks.some(input => input.checked)) {{
            event.preventDefault();
            alert('내보낼 영상을 하나 이상 선택하세요.');
          }}
        }});
        </script>
        """
        self._html("여러 자료 내보내기", content)

    def _job(self, query: dict[str, list[str]]) -> None:
        job = self.app.jobs.get(_first(query, "id"))
        if job is None:
            self._json({"status": "missing"}, status=HTTPStatus.NOT_FOUND)
        else:
            self._json(job)

    def _asset(self, query: dict[str, list[str]]) -> None:
        relative = _first(query, "path")
        candidate = (self.app.archive.root / relative).resolve()
        try:
            candidate.relative_to(self.app.archive.root)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        file_size = candidate.stat().st_size
        start = 0
        end = file_size - 1
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            requested = range_header.removeprefix("bytes=").split(",", 1)[0]
            first, _, last = requested.partition("-")
            if first:
                start = int(first)
            if last:
                end = min(int(last), end)
            if start > end or start >= file_size:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        else:
            self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        with candidate.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining and (block := source.read(min(1024 * 1024, remaining))):
                self.wfile.write(block)
                remaining -= len(block)

    def _download(self, data: dict[str, str]) -> None:
        if self.app.public_distribution:
            self._message_page(
                "공개 배포본에서는 URL 다운로드를 제공하지 않습니다.",
                "YouTube 정책을 준수하기 위해 재생목록 링크와 메타데이터만 가져옵니다. "
                "사용자가 권리를 보유한 파일은 로컬 파일 가져오기를 사용하세요.",
                is_error=True,
            )
            return
        url = data.get("url", "").strip()
        if not url:
            self.send_error(HTTPStatus.BAD_REQUEST, "URL is required")
            return
        mode = data.get("mode", "download")
        if mode not in {"subtitles", "video", "download"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid download mode")
            return
        subtitles_only = mode == "subtitles"
        download_subtitles = mode != "video"
        transcribe = mode == "download" and data.get("transcribe") == "on"
        options = DownloadOptions(
            playlist=data.get("playlist") or None,
            max_height=int(data.get("max_height", "1080")),
            download_subtitles=download_subtitles,
            subtitles_only=subtitles_only,
            transcribe_missing=transcribe,
        )

        def task() -> str:
            result = self.app.downloader.download(
                url,
                options=options,
                transcriber=self.app.transcriber if transcribe else None,
            )
            if not result.items:
                if subtitles_only:
                    return "가져올 자막이 없습니다. 영상에 공개 자막 또는 자동 자막이 있는지 확인하세요."
                return "새로 받을 항목이 없습니다. 이미 보관한 자료인지 확인하세요."
            if subtitles_only:
                return f"{len(result.items)}개 자막을 저장하고 검색 인덱스를 갱신했습니다."
            if mode == "video":
                return f"{len(result.items)}개 영상을 자막 없이 저장했습니다."
            return f"{len(result.items)}개 영상과 자막을 저장하고 검색 인덱스를 갱신했습니다."

        job_id = self.app.jobs.start("콘텐츠 수집", task)
        self._redirect(f"/?job={quote(job_id)}")

    def _import(self, data: dict[str, str]) -> None:
        path = Path(data.get("path", "")).expanduser()
        transcript_value = data.get("transcript", "").strip()
        transcript = Path(transcript_value).expanduser() if transcript_value else None
        try:
            item = self.app.archive.import_file(
                path,
                title=data.get("title") or None,
                rights_status="owned",
                transcript=transcript,
            )
            if transcript:
                self.app.archive.index_segments(
                    item.id, make_chunks(parse_subtitle(transcript))
                )
        except Exception as error:  # noqa: BLE001 - rendered locally
            self._message_page("가져오기 실패", str(error), is_error=True)
            return
        self._redirect(f"/item?id={quote(item.id)}")

    def _ask(self, data: dict[str, str]) -> None:
        question = data.get("question", "").strip()
        ai_status = self.app.local_ai.status()
        model = data.get("model") or self.app.local_ai.choose_model(
            ai_status.models, self.app.ollama_model
        )
        if not ai_status.running or not model or model not in ai_status.models:
            self._message_page(
                "로컬 AI 준비가 필요합니다.",
                "초기 설정에서 Ollama를 실행하고 AI 모델을 다운로드하세요.",
                is_error=True,
            )
            return
        try:
            answer = OllamaAssistant(self.app.archive, model=model).ask(question)
        except Exception as error:  # noqa: BLE001 - rendered locally
            self._message_page("AI 답변 실패", str(error), is_error=True)
            return
        sources = "".join(
            f"""
            <li><a href="{html.escape(hit.timestamp_url or hit.source_url or '#')}" target="_blank">
            [{index}] {html.escape(hit.title)} · {hit.timestamp}</a>
            <p>{html.escape(hit.text)}</p></li>
            """
            for index, hit in enumerate(answer.sources, start=1)
        )
        content = f"""
        {_back_link()}
        <section class="page-head"><p class="eyebrow">GROUNDED ANSWER</p><h1>{html.escape(question)}</h1></section>
        <article class="answer"><p>{html.escape(answer.text).replace(chr(10), '<br>')}</p></article>
        <section class="sources"><h2>사용한 근거</h2><ol>{sources}</ol></section>
        <form method="post" action="/export">
          <input type="hidden" name="question" value="{html.escape(question)}">
          <input type="hidden" name="model" value="{html.escape(model)}">
          <button>이 답변 다시 생성해 Markdown으로 저장</button>
        </form>
        """
        self._html("AI 답변", content)

    def _transcribe(self, data: dict[str, str]) -> None:
        item_id = data.get("item_id", "")

        def task() -> str:
            item = self.app.transcriber.transcribe_item(item_id)
            return f"'{item.title}' 전사와 검색 인덱스를 완료했습니다."

        job_id = self.app.jobs.start("Whisper 전사", task)
        self._redirect(f"/?job={quote(job_id)}")

    def _export(self, data: dict[str, str]) -> None:
        item_id = data.get("item_id")
        playlist = data.get("playlist", "").strip()
        selected_ids = {
            key.removeprefix("selected_")
            for key in data
            if key.startswith("selected_")
        }
        question = data.get("question")
        model = data.get("model") or self.app.ollama_model
        try:
            if item_id:
                item = self.app.archive.get_item(item_id)
                if item is None:
                    raise ValueError("자료를 찾지 못했습니다.")
                path = export_item_markdown(self.app.archive, item)
            elif playlist:
                items = sorted(
                    self.app.archive.list_items(playlist=playlist),
                    key=_playlist_item_order,
                )
                path = export_items_markdown(self.app.archive, items, playlist)
            elif selected_ids:
                items = [
                    item
                    for item in self.app.archive.list_items()
                    if item.id in selected_ids
                ]
                title = data.get("collection_title", "").strip()
                path = export_items_markdown(
                    self.app.archive,
                    items,
                    title or f"선택 자료 {len(items)}개",
                )
            elif question:
                answer = OllamaAssistant(self.app.archive, model=model).ask(question)
                path = export_answer_markdown(self.app.archive, question, answer)
            else:
                raise ValueError("내보낼 자료가 없습니다.")
        except Exception as error:  # noqa: BLE001 - rendered locally
            self._message_page("내보내기 실패", str(error), is_error=True)
            return
        self._message_page("내보내기 완료", f"저장 위치: {path}")

    def _youtube_connect(self, data: dict[str, str]) -> None:
        if (
            self.app.public_distribution
            and data.get("policy_accepted") != "on"
        ):
            self._message_page(
                "약관 동의가 필요합니다.",
                "Google 계정을 연결하기 전에 개인정보처리방침과 이용약관을 확인하고 "
                "동의해 주세요.",
                is_error=True,
            )
            return
        credentials_path = data.get("credentials_path", "").strip()
        try:
            if credentials_path:
                self.app.youtube.install_client_config(credentials_path)
            authorization_url = self.app.youtube.authorization_url(
                self.app.oauth_redirect_uri
            )
            opened = webbrowser.open(authorization_url)
        except Exception as error:  # noqa: BLE001 - rendered locally
            self._message_page("YouTube 연결 실패", str(error), is_error=True)
            return
        content = f"""
        {_back_link()}
        <section class="message">
          <p class="eyebrow">GOOGLE SIGN-IN</p>
          <h1>로그인 창을 열었습니다.</h1>
          <p>{'기본 브라우저에서' if opened else '아래 링크에서'} Google 계정을 선택하고 YouTube 읽기 권한을 승인하세요.</p>
          <a class="oauth-link" href="{html.escape(authorization_url)}" target="_blank">Google 로그인 열기 ↗</a>
          <p class="muted">승인이 끝나면 자동으로 이 앱으로 돌아옵니다.</p>
        </section>
        """
        self._html("Google 로그인", content)

    def _youtube_callback(self, query: dict[str, list[str]]) -> None:
        error = _first(query, "error")
        if error:
            if error == "access_denied":
                self._youtube_access_denied(query)
                return
            self._message_page(
                "YouTube 연결 취소",
                _first(query, "error_description") or error,
                is_error=True,
            )
            return
        try:
            self.app.youtube.exchange_callback(
                _first(query, "code"), _first(query, "state")
            )
        except Exception as callback_error:  # noqa: BLE001 - rendered locally
            self._message_page(
                "YouTube 연결 실패", str(callback_error), is_error=True
            )
            return
        self._redirect("/youtube?connected=1")

    def _youtube_disconnect(self) -> None:
        revoked = self.app.youtube.disconnect()
        deleted = (
            self.app.archive.delete_google_authorized_items()
            if self.app.public_distribution
            else 0
        )
        details = ["이 컴퓨터의 OAuth 토큰을 삭제했습니다."]
        if revoked:
            details.append("Google에도 접근 권한 폐기를 요청했습니다.")
        if deleted:
            details.append(f"Google 권한으로 가져온 항목 {deleted}개를 삭제했습니다.")
        self._message_page("YouTube 계정 연결을 해제했습니다.", " ".join(details))

    def _youtube_access_denied(self, query: dict[str, list[str]]) -> None:
        project_id = self.app.youtube.project_id
        project_parameter = (
            f"?project={quote(project_id)}"
            if project_id
            else ""
        )
        detail = _first(query, "error_description")
        content = f"""
        {_back_link()}
        <section class="message error api-action">
          <p class="eyebrow">GOOGLE OAUTH ACCESS DENIED</p>
          <h1>이 Google 계정은 아직 앱 사용 대상이 아닙니다.</h1>
          <p>OAuth 앱이 테스트 상태라면 Google Auth Platform의 테스트 사용자 목록에 등록된 계정만 연결할 수 있습니다.</p>
          <ol>
            <li>개발 중에는 <strong>Audience → Test users</strong>에 이 계정을 추가합니다.</li>
            <li>일반 배포 전에는 앱을 <strong>In production</strong>으로 전환합니다.</li>
            <li><code>youtube.readonly</code> 범위의 Google 검증을 완료합니다.</li>
          </ol>
          <div class="api-actions">
            <a class="oauth-link" href="https://console.cloud.google.com/auth/audience{project_parameter}" target="_blank">테스트 사용자 관리 ↗</a>
            <a class="retry-link" href="/setup">설정 화면으로 돌아가기</a>
          </div>
          <p class="muted">테스트 상태의 승인은 7일 후 만료됩니다. {html.escape(detail)}</p>
        </section>
        """
        self._html("Google OAuth 접근 차단", content)

    def _privacy(self) -> None:
        self._html("개인정보처리방침", _privacy_content())

    def _terms(self) -> None:
        self._html("이용약관", _terms_content())

    def _ai_start(self) -> None:
        job_id = self.app.jobs.start("Ollama 실행", self.app.local_ai.start)
        self._redirect(f"/setup?job={quote(job_id)}")

    def _ai_pull(self, data: dict[str, str]) -> None:
        model = data.get("model", DEFAULT_OLLAMA_MODEL).strip()

        def task() -> str:
            if not self.app.local_ai.status().running:
                self.app.local_ai.start()
            return self.app.local_ai.pull_model(model)

        job_id = self.app.jobs.start("AI 모델 다운로드", task)
        self._redirect(f"/setup?job={quote(job_id)}")

    def _youtube_import(self, data: dict[str, str]) -> None:
        playlist_id = data.get("playlist_id", "").strip()
        title = data.get("title", "").strip() or playlist_id
        mode = data.get("mode", "catalog")
        transcribe = data.get("transcribe") == "on"
        if mode not in {"catalog", "subtitles", "video", "download"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "invalid import mode")
            return
        if self.app.public_distribution and mode != "catalog":
            self._message_page(
                "공개 배포본에서는 목록만 가져올 수 있습니다.",
                "YouTube API 정책에 따라 영상, 자막 또는 오프라인 사본 저장 기능을 "
                "Google 계정 연동과 함께 제공하지 않습니다.",
                is_error=True,
            )
            return
        if not playlist_id:
            self.send_error(HTTPStatus.BAD_REQUEST, "playlist_id is required")
            return

        def task() -> str:
            playlist_items = self.app.youtube.list_playlist_items(playlist_id)
            registered = 0
            saved = 0
            failures: list[str] = []
            for playlist_item in playlist_items:
                self.app.archive.add_url(
                    playlist_item.url,
                    playlist_item.title,
                    rights_status="reference",
                    platform="Youtube",
                    playlist=title,
                    metadata={
                        "youtube_playlist_id": playlist_id,
                        "youtube_position": playlist_item.position,
                        "creator": playlist_item.creator,
                        "published_at": playlist_item.published_at,
                        "thumbnail_url": playlist_item.thumbnail_url,
                        "google_authorized_data": self.app.public_distribution,
                    },
                )
                registered += 1
                if mode == "catalog":
                    continue
                try:
                    subtitles_only = mode == "subtitles"
                    download_subtitles = mode != "video"
                    should_transcribe = mode == "download" and transcribe
                    result = self.app.downloader.download(
                        playlist_item.url,
                        options=DownloadOptions(
                            playlist=title,
                            download_subtitles=download_subtitles,
                            subtitles_only=subtitles_only,
                            transcribe_missing=should_transcribe,
                        ),
                        transcriber=(
                            self.app.transcriber if should_transcribe else None
                        ),
                    )
                    if result.items:
                        saved += len(result.items)
                    else:
                        failures.append(playlist_item.title)
                except Exception as error:  # noqa: BLE001 - continue playlist import
                    failures.append(f"{playlist_item.title}: {error}")
            message = f"{title}: {registered}개 항목을 등록했습니다."
            if mode == "subtitles":
                message += f" 자막은 {saved}개 저장했습니다."
            elif mode == "video":
                message += f" 자막 없이 저장한 영상은 {saved}개입니다."
            elif mode == "download":
                message += f" 영상과 자막을 저장한 항목은 {saved}개입니다."
            if failures:
                message += (
                    f" {len(failures)}개는 이미 보관됐거나 해당 파일에 접근할 수 없어 "
                    "목록만 남겼습니다."
                )
            return message

        job_id = self.app.jobs.start(f"{title} 가져오기", task)
        self._redirect(f"/?job={quote(job_id)}")

    def _form_data(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        return {key: values[0] for key, values in parse_qs(body).items()}

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _message_page(self, title: str, message: str, is_error: bool = False) -> None:
        content = f"""
        {_back_link()}
        <section class="message {'error' if is_error else ''}">
          <p class="eyebrow">STATUS</p><h1>{html.escape(title)}</h1>
          <p>{html.escape(message)}</p>
        </section>
        """
        self._html(title, content)

    def _html(
        self,
        title: str,
        content: str,
        job_id: str | None = None,
        job_return_to: str = "/",
    ) -> None:
        script = (
            """
            <script>
            const box = document.querySelector('#job');
            const message = document.querySelector('#job-message');
            async function poll() {
              const response = await fetch('/api/job?id=' + box.dataset.job);
              const job = await response.json();
              box.className = 'job ' + job.status;
              message.textContent = job.message || '진행 중...';
              if (job.status === 'running') setTimeout(poll, 1500);
              else if (job.status === 'done') setTimeout(() => location.href = __RETURN_TO__, 1800);
            }
            if (box) poll();
            </script>
            """.replace("__RETURN_TO__", json.dumps(job_return_to))
            if job_id
            else ""
        )
        body = PAGE.format(
            title=html.escape(title),
            content=content,
            script=script,
        ).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _item_card(item: ArchiveItem) -> str:
    cover = (
        f'<img src="/asset?path={quote(item.thumbnail_path)}" alt="">'
        if item.thumbnail_path
        else '<div class="cover-placeholder">SB</div>'
    )
    return f"""
    <a class="card" href="/item?id={quote(item.id)}">
      <div class="cover">{cover}<span>{html.escape(item.status)}</span></div>
      <div class="card-body">
        <p>{html.escape(item.creator or item.platform or "LOCAL")}</p>
        <h3>{html.escape(item.title)}</h3>
        <div><span>{html.escape(item.playlist or "Unsorted")}</span><span>{html.escape(item.rights_status)}</span></div>
      </div>
    </a>
    """


def _playlist_export_form(item: ArchiveItem) -> str:
    if not item.playlist:
        return ""
    playlist = html.escape(item.playlist)
    return (
        '<form method="post" action="/export">'
        f'<input type="hidden" name="playlist" value="{playlist}">'
        f'<button class="secondary">{playlist} 전체 내보내기</button>'
        "</form>"
    )


def _playlist_item_order(item: ArchiveItem) -> tuple[int, str]:
    position = item.metadata.get("youtube_position")
    try:
        return int(position), item.created_at
    except (TypeError, ValueError):
        return 1_000_000_000, item.created_at


def _playlist_export_card(
    playlist: str, items: list[ArchiveItem]
) -> str:
    transcript_count = sum(bool(item.transcript_path) for item in items)
    safe_playlist = html.escape(playlist)
    return f"""
    <article class="export-playlist-card">
      <p class="eyebrow">PLAYLIST</p>
      <h3>{safe_playlist}</h3>
      <p>{len(items)}개 자료 · 자막 {transcript_count}개</p>
      <form method="post" action="/export">
        <input type="hidden" name="playlist" value="{safe_playlist}">
        <button>전체를 하나의 Markdown으로 내보내기</button>
      </form>
    </article>
    """


def _export_item_row(item: ArchiveItem) -> str:
    status = "자막 있음" if item.transcript_path else "자막 없음"
    return f"""
    <label class="export-row">
      <input type="checkbox" name="selected_{item.id}" value="1">
      <span>
        <strong>{html.escape(item.title)}</strong>
        <small>{html.escape(item.playlist or "Unsorted")} · {status}</small>
      </span>
      <a href="/item?id={quote(item.id)}">내용 보기</a>
    </label>
    """


def _capture_panel(public_distribution: bool) -> str:
    local_import = """
    <details open>
      <summary>로컬 파일 가져오기</summary>
      <form method="post" action="/import">
        <label>이 컴퓨터의 파일 경로</label>
        <input name="path" placeholder="/Users/me/Movies/video.mp4" required>
        <label>제목</label><input name="title" placeholder="선택 사항">
        <label>자막 경로</label><input name="transcript" placeholder="/path/to/subtitle.srt">
        <button type="submit" class="secondary">파일 가져오기</button>
      </form>
    </details>
    """
    if public_distribution:
        return f"""
        <article class="panel capture">
          <div class="panel-title"><span>01</span><h2>자료 수집</h2></div>
          <section class="inline-setup">
            <strong>YouTube는 링크와 메타데이터만 가져옵니다.</strong>
            <p>Google 검증 및 YouTube 정책을 준수하는 공개 배포 모드입니다. 재생목록은 위의 YouTube 연결에서 카탈로그에 등록하세요.</p>
          </section>
          {local_import}
        </article>
        """
    return f"""
    <article class="panel capture">
      <div class="panel-title"><span>01</span><h2>링크 수집</h2></div>
      <form method="post" action="/download">
        <label>영상 또는 플레이리스트 URL</label>
        <input name="url" type="url" placeholder="https://www.youtube.com/..." required>
        <div class="form-row">
          <div><label>컬렉션</label><input name="playlist" placeholder="예: AI 공부"></div>
          <div><label>최대 화질</label>
            <select name="max_height">
              <option value="1080">1080p</option>
              <option value="720">720p</option>
              <option value="2160">4K</option>
            </select>
          </div>
        </div>
        <label class="check"><input type="checkbox" name="transcribe" checked> 영상+자막 저장 시 자막이 없으면 Whisper로 전사</label>
        <div class="capture-actions">
          <button type="submit" name="mode" value="subtitles" class="secondary">자막만 저장</button>
          <button type="submit" name="mode" value="video" class="secondary">영상만 저장</button>
          <button type="submit" name="mode" value="download">영상+자막 저장</button>
        </div>
      </form>
      {local_import}
    </article>
    """


def _privacy_content() -> str:
    info = public_info()
    contact = _public_contact(info.operator_name, info.support_email)
    return f"""
    {_back_link()}
    <section class="page-head">
      <p class="eyebrow">PRIVACY</p>
      <h1>개인정보처리방침</h1>
      <p>Second Brain Archive는 Google 계정 데이터와 사용자의 자료를 로컬 컴퓨터에서 처리합니다.</p>
    </section>
    <section class="oauth-note policy-document">
      <h2>Google 및 YouTube 데이터</h2>
      <p>앱은 사용자가 승인한 <code>youtube.readonly</code> 권한으로 YouTube 계정의 재생목록과 재생목록 항목을 읽습니다. 계정이나 YouTube 콘텐츠를 수정하지 않습니다.</p>
      <p>공개 배포 모드에서는 YouTube 영상, 음성 또는 자막의 오프라인 사본을 저장하지 않고 원본 링크와 메타데이터만 로컬 카탈로그에 등록합니다.</p>
      <h2>저장과 공유</h2>
      <p>OAuth 토큰, 재생목록 메타데이터와 로컬 아카이브는 사용자의 컴퓨터에만 저장되며 개발자 서버, 광고 서비스 또는 데이터 판매자에게 전송되지 않습니다.</p>
      <p>Google API에서 받은 데이터의 사용과 전송은 <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank">Google API Services User Data Policy</a>와 Limited Use 요구사항을 준수합니다.</p>
      <h2>삭제와 권한 철회</h2>
      <p>앱의 계정 연결 해제를 사용하면 로컬 OAuth 토큰을 삭제하고 Google에 토큰 폐기를 요청하며, Google 권한으로 가져온 카탈로그 항목을 삭제합니다.</p>
      <p><a href="https://security.google.com/settings/security/permissions" target="_blank">Google 계정 보안 설정</a>에서도 언제든 앱 접근 권한을 철회할 수 있습니다.</p>
      <h2>문의</h2>
      <p>{contact}</p>
    </section>
    """


def _terms_content() -> str:
    info = public_info()
    contact = _public_contact(info.operator_name, info.support_email)
    return f"""
    {_back_link()}
    <section class="page-head">
      <p class="eyebrow">TERMS</p>
      <h1>이용약관</h1>
      <p>앱을 사용하면 아래 조건과 YouTube 이용약관에 동의하게 됩니다.</p>
    </section>
    <section class="oauth-note policy-document">
      <h2>YouTube 서비스</h2>
      <p>Google 계정 연결 기능은 YouTube API Services를 사용합니다. 사용자는 <a href="https://www.youtube.com/t/terms" target="_blank">YouTube 이용약관</a>과 <a href="https://policies.google.com/privacy" target="_blank">Google 개인정보처리방침</a>의 적용을 받습니다.</p>
      <h2>공개 배포 모드</h2>
      <p>YouTube 재생목록의 제목, 항목과 원본 링크를 개인 로컬 카탈로그에 표시합니다. YouTube 영상의 다운로드, 백업 또는 오프라인 재생 기능은 제공하지 않습니다.</p>
      <h2>사용자 자료</h2>
      <p>사용자는 자신이 권리를 보유하거나 적법하게 사용할 수 있는 로컬 파일만 가져와야 합니다. 앱은 사용자가 제공한 로컬 자료의 권리를 취득하지 않습니다.</p>
      <h2>변경과 문의</h2>
      <p>중요한 변경이 있으면 적용일과 변경 내용을 고지합니다. {contact}</p>
    </section>
    """


def _public_contact(operator_name: str, support_email: str) -> str:
    if operator_name and support_email:
        escaped_email = html.escape(support_email)
        return (
            f"운영자: {html.escape(operator_name)} · "
            f'<a href="mailto:{escaped_email}">{escaped_email}</a>'
        )
    return "개발 빌드입니다. 공개 배포본에는 운영자와 지원 이메일이 표시됩니다."


def _youtube_playlist_card(
    playlist: YouTubePlaylist,
    *,
    allow_downloads: bool,
) -> str:
    thumbnail = (
        f'<img src="{html.escape(playlist.thumbnail_url)}" alt="">'
        if playlist.thumbnail_url
        else '<div class="playlist-thumb">YT</div>'
    )
    title = html.escape(playlist.title)
    playlist_id = html.escape(playlist.id)
    download_actions = (
        f"""
        <form method="post" action="/youtube/import">
          <input type="hidden" name="playlist_id" value="{playlist_id}">
          <input type="hidden" name="title" value="{title}">
          <input type="hidden" name="mode" value="subtitles">
          <button class="secondary">자막만 저장</button>
        </form>
        <form method="post" action="/youtube/import">
          <input type="hidden" name="playlist_id" value="{playlist_id}">
          <input type="hidden" name="title" value="{title}">
          <input type="hidden" name="mode" value="video">
          <button class="secondary">영상만 저장</button>
        </form>
        <form method="post" action="/youtube/import">
          <input type="hidden" name="playlist_id" value="{playlist_id}">
          <input type="hidden" name="title" value="{title}">
          <input type="hidden" name="mode" value="download">
          <label class="check"><input type="checkbox" name="transcribe" checked> 자막 없으면 전사</label>
          <button>영상+자막 저장</button>
        </form>
        """
        if allow_downloads
        else '<p class="muted">공개 배포 모드에서는 링크와 메타데이터만 가져옵니다.</p>'
    )
    return f"""
    <article class="playlist-card">
      {thumbnail}
      <div class="playlist-info">
        <h2>{title}</h2>
        <div class="playlist-meta">
          <span>{html.escape(playlist.privacy_status)}</span>
          <span>{playlist.item_count}개 영상</span>
        </div>
        <div class="playlist-actions">
          <form method="post" action="/youtube/import">
            <input type="hidden" name="playlist_id" value="{playlist_id}">
            <input type="hidden" name="title" value="{title}">
            <input type="hidden" name="mode" value="catalog">
            <button class="secondary">목록만 가져오기</button>
          </form>
          {download_actions}
        </div>
      </div>
    </article>
    """


def _stat(label: str, value: int) -> str:
    return f'<div><strong>{value:,}</strong><span>{html.escape(label)}</span></div>'


def _ai_status_title(status: LocalAIStatus) -> str:
    if status.ready:
        return "로컬 AI 준비 완료"
    if status.running:
        return "AI 모델 다운로드 필요"
    if status.installed:
        return "Ollama 실행 필요"
    return "로컬 AI 설치 필요"


def _ai_status_message(status: LocalAIStatus) -> str:
    if status.ready:
        return f"이 컴퓨터에 설치된 {len(status.models)}개 모델을 사용할 수 있습니다."
    if status.running:
        return "Ollama는 실행 중이며 사용할 모델만 받으면 됩니다."
    if status.installed:
        return "설치된 Ollama를 실행하면 로컬 질문 기능을 사용할 수 있습니다."
    return "Ollama와 권장 모델을 한 번 준비하면 이후에는 로컬에서 동작합니다."


def _ai_question_form(status: LocalAIStatus, preferred: str) -> str:
    if not status.ready:
        return f"""
        <section class="inline-setup">
          <strong>{_ai_status_title(status)}</strong>
          <p>{_ai_status_message(status)}</p>
          <a class="action-link" href="/setup">로컬 AI 준비하기</a>
        </section>
        """
    selected = OllamaRuntime.choose_model(status.models, preferred)
    options = "".join(
        f'<option value="{html.escape(model)}"'
        f'{" selected" if model == selected else ""}>'
        f'{html.escape(OllamaRuntime.label(model))}</option>'
        for model in status.models
    )
    return f"""
    <form method="post" action="/ask">
      <label>AI에게 질문</label>
      <textarea name="question" rows="4" placeholder="저장한 자료들이 공통으로 말하는 핵심은?" required></textarea>
      <label>이 컴퓨터에 설치된 모델</label>
      <select name="model">{options}</select>
      <button type="submit">근거와 함께 답변</button>
    </form>
    """


def _youtube_error_panel(
    api_error: YouTubeAPIError | None, error_message: str
) -> str:
    if api_error and api_error.reason == "SERVICE_DISABLED" and api_error.activation_url:
        return f"""
        <section class="message error api-action">
          <p class="eyebrow">API SETUP REQUIRED</p>
          <h2>YouTube Data API v3를 활성화해야 합니다.</h2>
          <p>Google 계정 연결은 완료됐지만, OAuth 클라이언트를 만든 Cloud 프로젝트에서 YouTube API가 꺼져 있습니다.</p>
          <div class="api-actions">
            <a class="oauth-link" href="{html.escape(api_error.activation_url)}" target="_blank">해당 프로젝트에서 API 활성화 ↗</a>
            <a class="retry-link" href="/youtube">활성화 후 다시 불러오기</a>
          </div>
          <p class="muted">활성화 직후에는 Google 시스템에 반영될 때까지 몇 분 걸릴 수 있습니다. 계정 연결을 해제하거나 다시 로그인할 필요는 없습니다.</p>
        </section>
        """
    message = str(api_error) if api_error else error_message
    if not message:
        return ""
    return f'<div class="message error"><strong>불러오기 실패</strong><p>{html.escape(message)}</p></div>'


def _empty_state(
    message: str = "아직 보관한 자료가 없습니다.",
    *,
    title: str = "아카이브가 비어 있습니다.",
) -> str:
    return f'<div class="empty"><strong>{html.escape(title)}</strong><p>{html.escape(message)}</p></div>'


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    return values[0] if values else ""


def _source_link(url: str | None, label: str) -> str:
    if not url:
        return ""
    return f'<a class="source-link" href="{html.escape(url)}" target="_blank">{html.escape(label)} ↗</a>'


def _back_link() -> str:
    return '<a class="back" href="/">← 아카이브로 돌아가기</a>'


def _timestamp_url(url: str | None, seconds: float) -> str | None:
    if not url:
        return None
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}t={int(seconds)}s"


def _format_seconds(value: float) -> str:
    seconds = int(value)
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _transcribe_form(item: ArchiveItem) -> str:
    if not item.media_path:
        return ""
    label = "다시 전사" if item.transcript_path else "Whisper로 전사"
    return (
        '<form method="post" action="/transcribe">'
        f'<input type="hidden" name="item_id" value="{item.id}">'
        f'<button class="secondary">{label}</button></form>'
    )


PAGE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --ink:#191a17; --paper:#f2f0e9; --panel:#fbfaf6; --line:#d7d3c6;
      --acid:#d9ff45; --blue:#3f63ff; --muted:#6d6d66; --danger:#b72f2f;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--paper); color:var(--ink); font-family:Inter, Pretendard, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body::before {{ content:""; display:block; height:8px; background:var(--ink); }}
    footer {{ width:min(1180px, calc(100% - 40px)); margin:-50px auto 45px; color:var(--muted); font-size:13px; }}
    main {{ width:min(1180px, calc(100% - 40px)); margin:0 auto; padding:54px 0 90px; }}
    h1,h2,h3,p {{ margin-top:0; }} h1 {{ font-size:clamp(42px,7vw,84px); line-height:.98; letter-spacing:-.055em; }}
    h1 span {{ color:var(--blue); }} h2 {{ font-size:30px; letter-spacing:-.035em; }} a {{ color:inherit; }}
    .eyebrow {{ font-size:12px; font-weight:800; letter-spacing:.16em; color:var(--blue); }}
    .hero {{ display:grid; grid-template-columns:1.35fr .65fr; gap:50px; align-items:end; margin-bottom:42px; }}
    .lede {{ max-width:620px; font-size:18px; line-height:1.65; color:var(--muted); }}
    .stats {{ display:grid; grid-template-columns:1fr 1fr; border:1px solid var(--ink); }}
    .stats div {{ min-height:120px; padding:22px; display:flex; flex-direction:column; justify-content:space-between; border:1px solid var(--ink); margin:-1px 0 0 -1px; }}
    .stats strong {{ font-size:38px; }} .stats span {{ color:var(--muted); font-size:13px; }}
    .workspace {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; margin-bottom:70px; }}
    .account-strip {{ border:1px solid var(--ink); background:var(--acid); padding:18px 22px; display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:20px; }}
    .account-strip div {{ display:flex; align-items:center; gap:14px; flex-wrap:wrap; }} .account-strip p {{ margin:0; color:var(--ink); }}
    .account-strip strong {{ font-size:18px; }} .account-strip span {{ color:#4e4e45; }} .account-strip a {{ background:var(--ink); color:white; text-decoration:none; padding:12px 16px; font-weight:800; white-space:nowrap; }}
    .ai-strip {{ background:#dce5ff; }}
    .panel {{ background:var(--panel); border:1px solid var(--ink); padding:28px; box-shadow:6px 6px 0 var(--ink); }}
    .panel-title {{ display:flex; gap:14px; align-items:center; border-bottom:1px solid var(--line); margin-bottom:25px; }}
    .panel-title span {{ background:var(--acid); border:1px solid var(--ink); padding:6px 8px; font-weight:800; }} .panel-title h2 {{ margin-bottom:18px; }}
    form {{ display:grid; gap:11px; margin-bottom:22px; }} label {{ font-size:13px; font-weight:750; }}
    input, textarea, select {{ width:100%; border:1px solid var(--ink); background:white; border-radius:0; padding:13px 14px; font:inherit; }}
    textarea {{ resize:vertical; }} input:focus,textarea:focus,select:focus {{ outline:3px solid rgba(63,99,255,.24); }}
    button {{ border:1px solid var(--ink); background:var(--ink); color:white; padding:14px 18px; font:inherit; font-weight:800; cursor:pointer; }}
    button:hover {{ background:var(--blue); }} button.secondary {{ background:var(--acid); color:var(--ink); }}
    .form-row {{ display:grid; grid-template-columns:1fr 150px; gap:12px; }} .check {{ display:flex; align-items:center; gap:8px; }}
    .capture-actions {{ display:grid; grid-template-columns:1fr 1fr 1.25fr; gap:8px; }} .capture-actions button {{ padding:12px 10px; }}
    .check input {{ width:auto; }} details {{ border-top:1px solid var(--line); padding-top:18px; }} summary {{ cursor:pointer; font-weight:800; margin-bottom:16px; }}
    .section-heading {{ display:flex; justify-content:space-between; align-items:end; border-bottom:2px solid var(--ink); margin-bottom:22px; gap:20px; }}
    .section-heading h2 {{ margin-bottom:14px; }} .section-heading > span {{ margin-bottom:16px; color:var(--muted); }}
    .section-actions {{ display:flex; align-items:center; gap:14px; margin-bottom:12px; }} .section-actions span {{ color:var(--muted); }} .section-actions a,.action-link {{ background:var(--acid); border:1px solid var(--ink); padding:10px 13px; font-weight:800; text-decoration:none; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:20px; }}
    .card {{ text-decoration:none; background:var(--panel); border:1px solid var(--line); transition:.15s; }}
    .card:hover {{ transform:translateY(-4px); border-color:var(--ink); box-shadow:5px 5px 0 var(--ink); }}
    .cover {{ height:175px; background:#dedbd0; position:relative; overflow:hidden; }} .cover img {{ width:100%; height:100%; object-fit:cover; }}
    .cover > span {{ position:absolute; left:10px; top:10px; background:var(--acid); border:1px solid var(--ink); padding:4px 7px; font-size:11px; font-weight:800; }}
    .cover-placeholder {{ height:100%; display:grid; place-items:center; font-weight:900; font-size:48px; color:#aaa69a; }}
    .card-body {{ padding:18px; }} .card-body > p {{ color:var(--blue); font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
    .card-body h3 {{ font-size:19px; line-height:1.35; min-height:52px; }} .card-body > div {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .card-body span,.badges span {{ font-size:11px; border:1px solid var(--line); padding:5px 7px; color:var(--muted); }}
    .job {{ padding:18px 20px; margin:-10px 0 30px; border:1px solid var(--ink); background:#fff3b0; display:flex; gap:14px; }}
    .job.done {{ background:#d9ffcf; }} .job.error,.message.error {{ background:#ffe0dc; color:var(--danger); }}
    .back {{ display:inline-block; margin-bottom:40px; font-weight:800; text-decoration:none; }}
    .page-head {{ max-width:900px; margin-bottom:34px; }} .page-head h1 {{ font-size:clamp(38px,6vw,68px); }}
    .inline-search {{ display:grid; grid-template-columns:1fr auto; margin-bottom:32px; }}
    .result {{ display:grid; grid-template-columns:105px 1fr; gap:25px; border-top:1px solid var(--line); padding:25px 0; }}
    .timestamp {{ font-family:ui-monospace,monospace; color:var(--blue); font-weight:800; }}
    .result h3 {{ font-size:21px; }} .result p {{ line-height:1.7; color:#42423d; }} .source-link {{ display:inline-block; color:var(--blue); font-weight:800; margin-top:8px; }}
    .detail-head {{ display:grid; grid-template-columns:minmax(240px,420px) 1fr; gap:40px; align-items:center; margin-bottom:34px; }}
    .detail-head h1 {{ font-size:clamp(38px,5vw,66px); }} .detail-cover {{ width:100%; aspect-ratio:16/9; object-fit:cover; border:1px solid var(--ink); box-shadow:8px 8px 0 var(--ink); }}
    .badges,.actions {{ display:flex; gap:8px; margin:16px 0; flex-wrap:wrap; }} .actions form {{ margin:0; }}
    video {{ width:100%; max-height:660px; background:#000; margin-bottom:55px; }}
    .transcript-row {{ display:grid; grid-template-columns:105px 1fr; gap:24px; padding:18px 0; border-top:1px solid var(--line); }}
    .transcript-row > a {{ font-family:ui-monospace,monospace; font-weight:800; color:var(--blue); }} .transcript-row p {{ line-height:1.7; }}
    .answer {{ background:var(--panel); border:1px solid var(--ink); padding:34px; font-size:18px; line-height:1.8; box-shadow:7px 7px 0 var(--acid); margin-bottom:42px; }}
    .sources li {{ padding:16px 0; border-top:1px solid var(--line); }} .sources li > a {{ font-weight:800; color:var(--blue); }} .sources li p {{ color:var(--muted); line-height:1.6; }}
    .message,.empty {{ padding:40px; background:var(--panel); border:1px solid var(--line); }} .message h1 {{ font-size:54px; }}
    .oauth-setup,.oauth-note {{ background:var(--panel); border:1px solid var(--ink); padding:32px; max-width:900px; }} .oauth-setup li {{ margin:10px 0; line-height:1.6; }}
    .oauth-setup code,.oauth-note code {{ background:#ece9df; padding:2px 5px; }} .muted {{ color:var(--muted); line-height:1.6; }} .oauth-link {{ display:inline-block; background:var(--blue); color:white; padding:14px 18px; font-weight:800; text-decoration:none; margin:16px 0; }}
    .api-action {{ margin-bottom:28px; }} .api-action h2 {{ color:var(--ink); }} .api-actions {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; }} .retry-link {{ border:1px solid var(--ink); background:var(--acid); color:var(--ink); padding:13px 17px; font-weight:800; text-decoration:none; }}
    .youtube-head {{ display:flex; align-items:end; justify-content:space-between; gap:30px; max-width:none; }} .youtube-head form {{ margin:0; }}
    .playlist-grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:18px; margin-bottom:35px; }} .playlist-card {{ border:1px solid var(--ink); background:var(--panel); display:grid; grid-template-columns:180px 1fr; min-height:180px; }}
    .playlist-card img,.playlist-thumb {{ width:180px; height:100%; min-height:180px; object-fit:cover; background:#dedbd0; }} .playlist-thumb {{ display:grid; place-items:center; font-size:38px; font-weight:900; color:#aaa69a; }}
    .playlist-info {{ padding:20px; }} .playlist-info h2 {{ font-size:22px; margin-bottom:8px; }} .playlist-info > p {{ color:var(--muted); }} .playlist-meta {{ display:flex; gap:6px; margin-bottom:16px; }} .playlist-meta span {{ border:1px solid var(--line); padding:4px 7px; font-size:11px; }}
    .playlist-actions {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }} .playlist-actions form {{ margin:0; }} .playlist-actions button {{ width:100%; padding:11px; font-size:13px; }} .playlist-actions .check {{ grid-column:1/-1; }}
    .oauth-note {{ max-width:none; margin-top:30px; }}
    .setup-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
    .setup-card {{ position:relative; background:var(--panel); border:1px solid var(--ink); padding:32px; box-shadow:6px 6px 0 var(--ink); }}
    .step-number {{ position:absolute; right:20px; top:18px; font-size:42px; font-weight:900; color:#d4d1c7; }}
    .setup-card h2 {{ max-width:80%; }} .setup-card form {{ margin-top:18px; }}
    .developer-settings {{ margin-top:28px; }} .warning-note {{ color:var(--danger); font-weight:800; }}
    .policy-check {{ align-items:flex-start; line-height:1.5; }} .policy-check a {{ color:var(--blue); }}
    .policy-document {{ max-width:900px; }} .policy-document h2 {{ margin-top:32px; }} .policy-document p {{ line-height:1.75; }}
    .ready-note {{ border-left:5px solid var(--acid); padding:12px 15px; background:#f5ffd4; font-weight:750; }}
    .model-list {{ list-style:none; padding:0; margin:22px 0 0; border-top:1px solid var(--line); }}
    .model-list li {{ display:flex; justify-content:space-between; gap:15px; padding:13px 0; border-bottom:1px solid var(--line); }}
    .model-list span {{ color:var(--muted); font-family:ui-monospace,monospace; font-size:12px; }}
    .inline-setup {{ border:1px dashed var(--ink); padding:22px; background:#f4f2eb; }}
    .inline-setup p {{ color:var(--muted); line-height:1.55; }} .inline-setup .action-link {{ display:inline-block; }}
    .export-playlists {{ margin-bottom:55px; }} .export-playlist-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }}
    .export-playlist-card {{ background:var(--panel); border:1px solid var(--ink); padding:22px; }} .export-playlist-card h3 {{ font-size:22px; min-height:54px; }} .export-playlist-card p:not(.eyebrow) {{ color:var(--muted); }} .export-playlist-card form {{ margin:0; }} .export-playlist-card button {{ width:100%; }}
    .export-toolbar {{ position:sticky; top:0; z-index:3; display:grid; grid-template-columns:auto auto minmax(180px,1fr) auto; align-items:center; gap:12px; background:var(--acid); border:1px solid var(--ink); padding:14px; margin-bottom:12px; }} .export-toolbar label {{ margin:0; }} .export-toolbar > span {{ font-weight:800; white-space:nowrap; }}
    .export-rows {{ display:grid; gap:8px; }} .export-row {{ display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:14px; background:var(--panel); border:1px solid var(--line); padding:15px 17px; cursor:pointer; }} .export-row:hover {{ border-color:var(--ink); }} .export-row input {{ width:auto; }} .export-row span {{ display:grid; gap:5px; }} .export-row small {{ color:var(--muted); }} .export-row a {{ color:var(--blue); font-weight:800; }}
    @media(max-width:800px) {{ main {{ width:min(100% - 24px,1180px); padding-top:32px; }} .hero,.workspace,.detail-head,.setup-grid {{ grid-template-columns:1fr; }} .grid,.playlist-grid,.export-playlist-grid {{ grid-template-columns:1fr; }} .stats div {{ min-height:90px; }} .result,.transcript-row {{ grid-template-columns:1fr; gap:8px; }} .account-strip,.youtube-head,.section-heading {{ align-items:flex-start; flex-direction:column; }} .section-actions {{ margin-top:-12px; }} .playlist-card {{ grid-template-columns:1fr; }} .playlist-card img,.playlist-thumb {{ width:100%; height:190px; min-height:190px; }} .export-toolbar {{ position:static; grid-template-columns:1fr; }} .export-row {{ grid-template-columns:auto 1fr; }} .export-row a {{ grid-column:2; }} }}
  </style>
</head>
<body><main>{content}</main><footer><a href="/privacy">개인정보처리방침</a> · <a href="/terms">이용약관</a></footer>{script}</body>
</html>
"""
