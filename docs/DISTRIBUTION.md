# 일반 사용자용 배포 준비

일반 사용자는 Google Cloud 프로젝트나 OAuth JSON을 만들지 않습니다. 앱 제작자가
배포 전에 한 번 설정하고, 사용자는 `Google 계정으로 YouTube 연결` 버튼만
누릅니다.

## 배포 결과

한 저장소에서 다음 설치 파일을 각각 만듭니다.

| 사용자 | 설치 파일 | 기본 데이터 위치 |
|---|---|---|
| Apple Silicon Mac | `Second-Brain-Archive-macOS-arm64.dmg` | `~/Library/Application Support/Second Brain Archive` |
| Intel Mac | `Second-Brain-Archive-macOS-x86_64.dmg` | `~/Library/Application Support/Second Brain Archive` |
| Windows 64비트 | `Second-Brain-Archive-Windows-x64.exe` | `%LOCALAPPDATA%\Second Brain Archive` |

PyInstaller 결과물은 빌드한 운영체제와 CPU에 종속되므로 Windows와 macOS 빌드는
서로 다른 GitHub Actions 러너에서 수행합니다. 공개 배포본은 Google 및 YouTube
정책 준수를 위해 URL 다운로드 엔진을 포함하지 않습니다.

## 로컬 빌드

Apple Silicon Mac에서는 다음 명령으로 현재 CPU용 앱과 DMG를 만듭니다.

```bash
./scripts/build_macos.sh
```

Windows에서는 PowerShell과 Inno Setup 6가 설치된 환경에서 실행합니다.

```powershell
./scripts/build_windows.ps1
```

결과물은 `dist/`에 생성됩니다. 서명 환경변수가 없으면 테스트 가능한 미서명 또는
임시 서명 빌드가 만들어집니다. 일반 사용자에게 공개할 때는 아래 코드 서명이
필요합니다.

## 자동 릴리스

`.github/workflows/release.yml`은 다음 세 빌드를 병렬 실행합니다.

- GitHub `macos-14` 러너: Apple Silicon DMG
- GitHub `macos-15-intel` 러너: Intel DMG
- GitHub `windows-latest` 러너: Windows x64 설치 파일

GitHub 저장소의 Actions secrets에 다음 값을 등록합니다.

필수:

- `YOUTUBE_OAUTH_JSON_BASE64`: 운영용 데스크톱 OAuth JSON의 Base64

Actions variables:

- `SECOND_BRAIN_OPERATOR_NAME`: 개인정보처리방침에 표시할 운영자명
- `SECOND_BRAIN_SUPPORT_EMAIL`: 사용자 지원 이메일
- `SECOND_BRAIN_HOMEPAGE_URL`: HTTPS 공개 홈페이지
- `SECOND_BRAIN_JURISDICTION`: 약관 준거법 지역

현재 저장소에는 이태건, `ltg0971@gmail.com`,
`https://leetgeon.github.io/second-brain-archive`가 기본 공개 정보로 포함되어
있습니다. 위 variables는 다른 운영 환경에서 기본값을 변경할 때 사용합니다.

macOS 서명과 공증:

- `MACOS_CERTIFICATE_BASE64`: Developer ID Application 인증서 `.p12`의 Base64
- `MACOS_CERTIFICATE_PASSWORD`: `.p12` 암호
- `MACOS_KEYCHAIN_PASSWORD`: CI 임시 키체인 암호
- `APPLE_SIGNING_IDENTITY`: `Developer ID Application: ...`
- `APPLE_ID`: Apple Developer 계정 이메일
- `APPLE_TEAM_ID`: Apple Developer Team ID
- `APPLE_APP_PASSWORD`: 앱 전용 암호

Windows 코드 서명:

- `WINDOWS_CERTIFICATE_BASE64`: 코드 서명 인증서 `.pfx`의 Base64
- `WINDOWS_CERTIFICATE_PASSWORD`: `.pfx` 암호

태그를 올리면 두 운영체제의 설치 파일을 빌드하고 GitHub Release에 자동
첨부합니다.

```bash
git tag v0.2.0
git push origin v0.2.0
```

태그 없이 Actions의 `Build desktop installers`를 수동 실행하면 Release를
게시하지 않고 설치 파일을 Artifacts로만 검증할 수 있습니다.

`.github/workflows/pages.yml`은 같은 Actions variables로 OAuth 검증용 홈페이지,
개인정보처리방침과 이용약관을 GitHub Pages에 게시합니다.

## 서명 없이 배포하면

- macOS에서는 Gatekeeper가 확인되지 않은 개발자 경고를 표시합니다.
- Windows에서는 SmartScreen 경고가 표시될 수 있습니다.

내부 테스트에는 미서명 빌드를 사용할 수 있지만 공개 배포에는 Apple Developer
ID 서명과 공증, Windows 코드 서명을 권장합니다.

## Google OAuth

1. 운영용 Google Cloud 프로젝트에서 YouTube Data API v3를 활성화합니다.
2. OAuth 앱을 외부 사용자용으로 구성하고 홈페이지, 개인정보처리방침, 지원
   이메일과 소유 도메인을 등록합니다.
3. `youtube.readonly` 범위로 Google 검증을 완료합니다.
4. 데스크톱 앱 OAuth 클라이언트 JSON을 다운로드합니다.
5. 배포 빌드 전에 다음 명령을 실행합니다.

```bash
./scripts/configure_release_oauth.sh ~/Downloads/client_secret_....json
```

이 명령은 `src/second_brain_archive/youtube_oauth.json`을 생성합니다. 파일은
Git에서 제외되지만 Python 패키지와 Mac 앱 번들에는 포함됩니다. 데스크톱 OAuth
클라이언트는 비밀을 안전하게 숨길 수 없는 공개 클라이언트이므로 앱은 PKCE와
로컬 루프백 콜백을 사용합니다.

개인정보처리방침 초안은 [PRIVACY.md](PRIVACY.md)에 있습니다. 공개 검증을
신청하기 전에 운영자 정보와 지원 이메일을 채우고 HTTPS 웹사이트에 게시해야
합니다.

CI에서는 JSON 파일 대신 다음 환경변수를 주입할 수도 있습니다.

```bash
export SECOND_BRAIN_YOUTUBE_CLIENT_ID="...apps.googleusercontent.com"
export SECOND_BRAIN_YOUTUBE_CLIENT_SECRET="..."
```

기존 개인 OAuth JSON은 `data/secrets/youtube_client.json`에 남아 있으면 우선
사용됩니다. 개발 중인 계정 연결을 깨지 않기 위한 호환 동작입니다.

Testing 상태에서 다른 계정이 `403: access_denied`로 차단되면 Audience의 Test
users에 해당 계정을 추가해야 합니다. 테스트 승인은 7일 후 만료됩니다.

일반 사용자 배포에서는 Audience에서 `Publish app`을 눌러 `In production`으로
전환합니다. 이때부터 계정별 테스트 사용자 등록은 필요 없지만, Google 검증이
끝나기 전에는 검증되지 않은 앱 경고와 신규 사용자 100명 제한이 남습니다.

공개 검증 준비, 범위 설명과 데모 영상 체크리스트는
[GOOGLE_OAUTH_RELEASE.md](GOOGLE_OAUTH_RELEASE.md)에 있습니다.

### 공개 모드와 개인 모드

`build_macos.sh`, `build_windows.ps1`과 GitHub Actions는 기본적으로 `public`
프로필을 빌드합니다. 이 모드에서는 YouTube 재생목록의 링크와 메타데이터만
카탈로그에 등록합니다.

개인 개발 환경에서 기존 전체 기능을 검사하려면 다음과 같이 실행합니다.

```bash
SECOND_BRAIN_PROFILE=personal ./scripts/run.sh
```

YouTube API Services 정책은 API 클라이언트가 YouTube 시청각 콘텐츠의 다운로드,
백업 또는 오프라인 사본 저장을 제공하는 것을 금지합니다. 따라서 개인 모드의
다운로드 기능을 공용 검증 OAuth 클라이언트와 함께 배포하지 않습니다.

## 로컬 AI

Ollama 자체를 앱에 복제해 포함하지 않습니다. 설치 파일과 모델은 크고 업데이트
주기가 다르므로 초기 설정 화면에서 다음 흐름으로 준비합니다.

1. Ollama가 없으면 운영체제에 맞는 공식 설치 페이지를 제공합니다.
2. 설치됐지만 중지됐으면 앱에서 Ollama를 실행합니다.
3. 권장 모델 `gemma3:4b-it-qat`을 Ollama API로 다운로드합니다.
4. 질문 화면에는 실제 설치된 모델만 표시합니다.

권장 모델은 약 3.3GB입니다. 모델과 질문 데이터는 `~/.ollama`와 로컬 API에서만
처리되며 별도의 AI API 키가 필요하지 않습니다.

## 개인 개발 모드 선택 기능

개인 개발 모드에서는 공개 자막과 YouTube 자동 자막을 저장할 수 있습니다. 자막이
없는 영상에 새 자막을 생성하는 Whisper 전사는 macOS와 Windows의 네이티브 실행
파일 구성이 달라 공개 설치본에 포함하지 않습니다. 이 기능은 `whisper-cli`가
설치된 개인 개발 환경에서 활성화됩니다.
