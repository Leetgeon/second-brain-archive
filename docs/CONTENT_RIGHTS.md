# 콘텐츠 권리 정책

이 문서는 제품 동작 원칙이며 법률 자문이 아니다. 플랫폼 약관, 콘텐츠 라이선스,
거주 국가의 법률을 함께 확인해야 한다.

## 기본 규칙

URL을 저장하는 것과 콘텐츠 파일을 소유하는 것은 다르다. 타인이 게시한 영상을
내려받아도 저작권이나 소유권이 이전되지 않는다.

아카이브는 다음 상태를 사용한다.

| 상태 | 의미 | 기본 미디어 처리 |
|---|---|---|
| `owned` | 본인이 제작했거나 권리를 보유 | 가져오기 허용 |
| `licensed` | 보관·처리에 필요한 명시적 허락 보유 | 허락 범위에서 허용 |
| `public-domain` | 퍼블릭 도메인으로 확인 | 가져오기 허용 |
| `personal-use` | 개인 로컬 보관 목적으로 수집, 저작권 소유 의미 아님 | 사용자가 요청하면 수집 |
| `reference` | 링크와 메타데이터만 참조 | 원본 자동 수집 안 함 |
| `unknown` | 권리 상태를 아직 확인하지 못함 | 원본 자동 수집 금지 |

## YouTube 관련 경계

- 본인이 업로드한 영상은 Google Takeout 등 플랫폼이 제공하는 내보내기 기능을
  우선 사용한다.
- 공식 YouTube Data API의 자막 다운로드는 해당 영상을 편집할 권한이 있는
  계정에 한정된다.
- 계정 재생목록 목록은 공식 `youtube.readonly` OAuth 권한으로만 읽고 Google
  비밀번호나 브라우저 쿠키를 저장하지 않는다.
- 타인 영상의 로컬 보관은 사용자가 직접 요청한 경우 `personal-use`로 구분한다.
  이 표시는 저작권이나 재배포 권리를 주장하지 않으며 플랫폼 약관과 지역 법률은
  사용자가 별도로 확인해야 한다.
- 로컬 전사는 합법적으로 확보한 미디어 파일에 대해서만 수행한다.
- 로그인 쿠키, 접근 제한 우회, DRM 회피 기능은 프로젝트 범위에 넣지 않는다.

## 저장해야 하는 증빙

`licensed` 또는 `public-domain` 자료에는 가능하면 다음을 `rights_note` 또는
별도 증빙 파일로 남긴다.

- 라이선스 이름과 버전
- 권리자 또는 제공자
- 라이선스가 표시된 원본 URL
- 확인 날짜
- 개인 보관, AI 처리, 재배포 가능 여부

## AI 사용 원칙

- 외부 AI API에 원문을 전송할지 사용자가 선택할 수 있어야 한다.
- 개인적이거나 비공개인 자료는 기본적으로 로컬 처리한다.
- 생성된 요약은 원본을 대체하지 않으며 생성 모델과 처리 날짜를 기록한다.
- 답변과 노트는 원본 출처 및 타임스탬프를 포함한다.

## 참고한 공식 문서

- YouTube Terms of Service:
  https://www.youtube.com/static?template=terms
- YouTube Data API `captions.download`:
  https://developers.google.com/youtube/v3/docs/captions/download
- YouTube installed app OAuth:
  https://developers.google.com/youtube/v3/guides/auth/installed-apps
- YouTube Data API `playlists.list`:
  https://developers.google.com/youtube/v3/docs/playlists/list
- Google 데이터 내보내기:
  https://support.google.com/accounts/answer/3024190
