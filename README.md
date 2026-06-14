# Second Brain Archive

좋은 영상과 플레이리스트를 로컬에 보관하고, 자막 전체를 검색하며, 저장한 근거만
사용하는 AI에게 질문하는 개인 콘텐츠 아카이브입니다.

## 완성된 기능

- 공식 YouTube OAuth를 통한 내 계정 재생목록 목록 가져오기
- 공개 배포 모드의 재생목록 링크·메타데이터 카탈로그 등록
- 개인 개발 모드의 `yt-dlp` 기반 영상·자막 보관과 로컬 Whisper 전사
- 개인 개발 모드의 다운로드 기록 기반 중복 수집 방지
- SQLite FTS5 기반 한국어·영어 자막 검색
- 검색 결과의 원본 영상 타임스탬프 연결
- 로컬 Ollama 모델을 이용한 근거 기반 질의응답
- 영상별 노트와 AI 연구 결과의 Markdown 내보내기
- 터미널 없이 사용할 수 있는 로컬 웹 대시보드
- SHA-256 기반 동일 원본 중복 저장 방지

## 이 Mac에서 바로 실행

개발 모드에서는 다음 명령 하나로 실행합니다.

```bash
./scripts/run.sh
```

브라우저에서 <http://127.0.0.1:8765>를 엽니다. 기본 보관 위치는 프로젝트 안의
`data/`입니다.

Finder에서는 `Second Brain.command`를 더블클릭해 대시보드와 브라우저를 함께
열 수 있습니다.

## macOS와 Windows 설치본

배포 빌드는 운영체제별로 분리됩니다.

- macOS Apple Silicon: `Second-Brain-Archive-macOS-arm64.dmg`
- macOS Intel: `Second-Brain-Archive-macOS-x86_64.dmg`
- Windows 64비트: `Second-Brain-Archive-Windows-x64.exe`

Google 검증용 공개 설치본은 YouTube 정책에 따라 재생목록의 링크와 메타데이터만
가져오며 영상·음성·자막 다운로드 엔진을 포함하지 않습니다. 사용자가 소유한
로컬 파일 가져오기, 검색, Markdown 내보내기와 로컬 AI는 그대로 사용할 수
있습니다.

설치본의 사용자 자료는 앱 파일과 분리되어 업데이트 후에도 유지됩니다.

- macOS: `~/Library/Application Support/Second Brain Archive`
- Windows: `%LOCALAPPDATA%\Second Brain Archive`

빌드 및 GitHub Release 절차는 [배포 문서](docs/DISTRIBUTION.md)에 있습니다.

## 내 YouTube 계정 연결

대시보드의 `YouTube 연결`을 누르면 내 계정의 공개·일부공개·비공개 재생목록을
불러올 수 있습니다. 일반 사용자용 배포본에서는 `Google 계정으로 YouTube 연결`
버튼을 누르고 읽기 권한만 승인하면 됩니다.

소스에서 직접 실행하는 개발자는 기존처럼 개인 OAuth JSON을 등록할 수 있습니다.
일반 사용자용 OAuth 배포 준비는 [배포 문서](docs/DISTRIBUTION.md)를 참고하세요.
공개 앱은 Google Auth Platform에서 `In production`으로 전환하고
`youtube.readonly` 검증을 완료하므로 사용자가 테스트 계정이나 OAuth JSON을
등록하지 않습니다.

공개 홈페이지: <https://leetgeon.github.io/second-brain-archive>

연결 후 재생목록마다 다음 중 하나를 선택할 수 있습니다.

- 공개 배포 모드: `목록만 가져오기`로 제목, 메타데이터와 원본 URL 등록
- 개인 개발 모드: 자막만, 영상만 또는 영상+자막 저장 기능 유지

대시보드의 `여러 자료 Markdown 내보내기`에서는 재생목록 전체를 하나의
Markdown으로 합치거나, 원하는 영상만 체크해 선택 묶음 문서를 만들 수 있습니다.
각 영상의 원본 링크와 타임스탬프가 포함됩니다.

공개 배포 모드는 비공개 재생목록을 포함해 목록과 메타데이터까지만 저장합니다.
개인 개발 모드에서도 소유자에게만 공개된 비공개 영상은 공식 Data API가 원본
미디어를 제공하지 않으므로 목록과 메타데이터까지만 저장됩니다.

OAuth 클라이언트와 토큰은 사용자 데이터 폴더의 `secrets/`에 권한 `0600`으로
저장되며 Git과 일반 백업에서 제외됩니다. 소스 개발 모드의 기본 사용자 데이터
폴더는 프로젝트의 `data/`입니다.

## 로컬 AI 준비

초기 설정 화면은 Ollama 설치 여부, 실행 상태와 설치된 모델을 자동으로 확인합니다.
Ollama가 설치되어 있으면 앱에서 실행하고 권장 모델
`gemma3:4b-it-qat`을 다운로드할 수 있습니다. 질문 화면에는 실제로 이 컴퓨터에
설치된 모델만 표시되며 AI API 키는 필요하지 않습니다.

Ollama가 없는 사용자는 초기 설정 화면의 공식 설치 링크로 한 번 설치해야 합니다.
권장 모델은 약 3.3GB이며 모든 질문과 답변은 로컬 Ollama API에서 처리됩니다.

## 소스에서 처음 실행하는 Mac

```bash
brew install whisper-cpp ollama

/Users/mac/.pyenv/versions/3.12.13/bin/python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[build]"

second-brain --root data setup-whisper
second-brain --root data doctor
second-brain --root data serve
```

Whisper small 모델은 약 466MB입니다. 모델 위치는
`data/models/ggml-small.bin`입니다.

## CLI 사용법

```bash
# 단일 영상 또는 플레이리스트 보관
second-brain --root data download "https://www.youtube.com/watch?v=..."

# 자막이 없어도 전사하지 않고 우선 다운로드만
second-brain --root data download "URL" --no-transcribe

# 영상 없이 자막만 저장하고 검색 인덱스 생성
second-brain --root data download "URL" --subtitles-only

# 자막 없이 영상만 저장
second-brain --root data download "URL" --no-subs --no-transcribe

# 자막 검색
second-brain --root data search "검색할 문장"

# 저장된 근거만 사용해 Ollama에 질문
second-brain --root data ask "자료들이 공통으로 강조하는 내용은?" \
  --model llama3.1:8b --export

# 특정 자료를 Markdown 노트로 내보내기
second-brain --root data export ITEM_ID

# 데이터베이스와 원본 체크섬 확인
second-brain --root data verify
```

## 저장 구조

```text
data/
├── catalog.sqlite3
├── download-archive.txt
├── media/               # 원본 영상과 음성
├── transcripts/         # 자막과 Whisper 전사
├── thumbnails/          # 대표 이미지
├── descriptions/        # 원본 설명
├── records/             # 이식 가능한 JSON 매니페스트
├── exports/             # Obsidian에서 열 수 있는 Markdown
├── models/              # 로컬 Whisper 모델
└── staging/             # 처리 중 임시 파일
```

원본과 파생 데이터가 분리되어 있어 AI 모델이나 검색 방식을 바꿔도 수집한 자료는
그대로 남습니다.

## 권리 상태

다운로드 자료의 기본 상태는 `personal-use`입니다. 이는 로컬 개인 보관 목적이라는
기록이며 콘텐츠 저작권을 소유한다는 뜻이 아닙니다. 본인 제작물은 `owned`,
명시적인 허가가 있으면 `licensed`, 퍼블릭 도메인은 `public-domain`으로 변경할
수 있습니다.

플랫폼 약관과 콘텐츠 권리를 확인하고, 접근 제한이나 DRM을 우회하지 않는 범위에서
사용하세요. 자세한 기준은 [콘텐츠 권리 정책](docs/CONTENT_RIGHTS.md)에 있습니다.

외장 디스크 백업과 복구 절차는 [백업 문서](docs/BACKUP.md)를 참고하세요.

## 테스트

```bash
PYTHONPATH=src /Users/mac/.pyenv/versions/3.12.13/bin/python \
  -m unittest discover -s tests -v
```
