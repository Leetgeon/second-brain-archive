# Google OAuth 공개 전환 체크리스트

## 테스트와 공개 배포의 차이

`액세스 차단됨`과 `403: access_denied`는 OAuth 앱의 게시 상태가 `Testing`인데
로그인한 계정이 테스트 사용자로 등록되지 않았을 때 발생한다.

개발 중에만 테스트 사용자를 등록한다. 일반 배포에서는 Audience의 `Publish app`을
눌러 `In production`으로 전환하므로 사용자가 각자 Google Cloud에 등록할 필요가
없다.

단, `youtube.readonly`는 민감 범위다. 게시만 하고 검증받지 않으면 사용자가
검증되지 않은 앱 경고를 통과해야 하고 프로젝트 전체 수명 동안 신규 사용자
100명 제한이 적용된다. 경고와 제한 없이 배포하려면 Google OAuth 검증을 완료해야
한다.

## 현재 403을 임시로 해결하는 방법

1. [Google Auth Platform Audience](https://console.cloud.google.com/auth/audience?project=second-brain-archive-499306)를 연다.
2. `Test users`에서 `Add users`를 누른다.
3. 테스트할 Google 계정을 추가하고 저장한다.
4. 앱에서 Google 연결을 다시 시작한다.

Testing 상태는 최대 100명의 테스트 사용자만 허용하고, YouTube 읽기 권한과
갱신 토큰은 승인 후 7일이 지나면 만료된다.

## 공개 배포 모드

Google 검증을 받는 설치본은 `public` 프로필로 빌드한다.

```bash
SECOND_BRAIN_PROFILE=public ./scripts/build_macos.sh
```

이 모드에서는 다음만 제공한다.

- Google 계정의 재생목록과 항목 읽기
- 제목, 원본 YouTube 링크와 메타데이터를 로컬 카탈로그에 등록
- 사용자가 직접 소유한 로컬 파일 가져오기
- 로컬 검색, Markdown 내보내기와 로컬 AI

YouTube API Services Developer Policies에 따라 YouTube 영상·음성·자막 다운로드,
백업과 오프라인 사본 저장은 공개 OAuth 배포본에서 제공하지 않는다. 개인 개발
프로필은 별도 OAuth 프로젝트와 제한된 테스트 사용자 범위에서만 사용한다.

## 검증 전에 필요한 공개 웹페이지

동일한 소유 도메인에 HTTPS로 다음 페이지를 게시한다.

- 제품 홈페이지: 앱 기능과 로컬 처리 방식 설명
- 개인정보처리방침: `PRIVACY.md`를 기반으로 운영자 정보까지 완성
- 이용약관: `TERMS.md`를 기반으로 완성

Google Search Console에서 해당 도메인의 소유권을 확인하고 Auth Platform의
Authorized domains에 등록한다. 앱 이름, 홈페이지, 개인정보처리방침과 약관의
표현은 앱 화면 및 검증 영상과 일치해야 한다.

이 저장소의 `.github/workflows/pages.yml`은 동일한 정보로 세 페이지를 GitHub
Pages에 배포한다. 현재 기본 공개 정보는 다음과 같다.

```text
운영자: 이태건
지원 이메일: ltg0971@gmail.com
홈페이지: https://leetgeon.github.io/second-brain-archive
```

다른 배포 환경에서는 `SECOND_BRAIN_OPERATOR_NAME`,
`SECOND_BRAIN_SUPPORT_EMAIL`, `SECOND_BRAIN_HOMEPAGE_URL`,
`SECOND_BRAIN_JURISDICTION` Actions variables로 기본값을 덮어쓸 수 있다.
개인정보처리방침과 약관 주소는 각각 `/privacy/`, `/terms/`로 자동 생성된다.

## Google Auth Platform 설정

1. Branding에서 앱 이름, 지원 이메일, 홈페이지, 개인정보처리방침과 약관 URL을
   입력한다.
2. Audience의 User type을 `External`로 확인한다.
3. Data Access에는 다음 하나의 범위만 등록한다.

```text
https://www.googleapis.com/auth/youtube.readonly
```

4. 공개 준비가 끝나면 Audience에서 `Publish app`을 눌러 `In production`으로
   전환한다.
5. Verification Center에서 Branding과 Data Access 검증을 제출한다.

`Publish app` 직후부터 테스트 사용자 등록 없이 로그인할 수 있지만, 검증이
승인되기 전에는 경고와 100명 제한이 남는다.

## 범위 사용 설명 예시

```text
Second Brain Archive is a local-first desktop application. It uses the
youtube.readonly scope only to list the signed-in user's YouTube playlists,
including private playlists, and their playlist items. The user can select a
playlist and add its titles, metadata, and original YouTube links to a local
catalog on the user's own computer. The application does not modify YouTube
data, download YouTube audiovisual content, or transmit OAuth tokens or
authorized YouTube data to developer-operated servers. This read-only scope is
the narrowest scope that can access the user's private playlists.
```

## 검증 영상에 포함할 내용

영상은 일부공개 YouTube 영상으로 올리고 OAuth 화면 언어는 영어로 설정한다.

1. 배포된 데스크톱 앱 이름과 버전
2. 개인정보처리방침 및 이용약관 동의
3. `Google 계정으로 YouTube 연결` 클릭
4. 주소 표시줄에 OAuth 클라이언트 ID가 보이는 동의 화면
5. 정확히 `youtube.readonly` 하나만 요청하는 화면
6. 공개·비공개 재생목록 목록 표시
7. `목록만 가져오기`로 제목과 원본 링크가 로컬 카탈로그에 등록되는 과정
8. 영상 다운로드 기능이 공개 모드에 없다는 화면
9. `계정 연결 해제` 후 토큰과 Google 권한 데이터가 삭제되는 과정

민감 범위 검증은 Google 안내상 최대 약 10일이 걸릴 수 있다. 심사 중 앱 이름,
로고, 도메인, 범위 또는 OAuth 클라이언트를 바꾸지 않는다.

## 정식 릴리스 빌드 보호

GitHub Actions의 설치본 빌드는 다음 항목이 모두 있어야 진행된다.

- 위의 공개 신원 Actions variables
- 비밀값이 없는 `youtube_oauth_public.json`
- `SECOND_BRAIN_PROFILE=public`

누락된 값이 있으면 정식 릴리스 빌드는 실패한다. 로컬 개발 빌드는 기존처럼 빈
공개 신원 정보로도 실행할 수 있다.

전체 OAuth JSON과 `client_secret`은 GitHub Secret에도 업로드하지 않는다.
설치 앱은 비밀을 보관할 수 없고 Google의 데스크톱 OAuth 토큰 교환에서도
`client_secret`은 선택 사항이다. 공개 클라이언트 ID와 PKCE를 사용한다.
