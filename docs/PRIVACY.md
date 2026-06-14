# 개인정보처리방침 초안

최종 업데이트: 2026년 6월 14일

Second Brain Archive는 사용자의 영상 자료와 AI 질문을 사용자의 컴퓨터에 보관하고
처리하는 로컬 우선 애플리케이션입니다.

## Google 및 YouTube 데이터

앱은 사용자가 명시적으로 승인한 경우에만
`https://www.googleapis.com/auth/youtube.readonly` 권한을 사용합니다. 이 권한은
사용자의 YouTube 계정과 공개·일부공개·비공개 재생목록 및 재생목록 항목을 읽는 데
사용됩니다. 앱은 YouTube 계정을 수정하거나 영상을 업로드·삭제하지 않습니다.

OAuth 액세스 토큰과 갱신 토큰은 사용자의 컴퓨터 안 사용자 데이터 폴더의
`secrets/`에만 저장되며 앱 제작자의 서버로 전송되지 않습니다.

공개 배포 모드는 YouTube 영상, 음성 또는 자막의 오프라인 사본을 저장하지
않습니다. 재생목록의 제목, 항목 메타데이터와 원본 YouTube 링크만 사용자의 로컬
카탈로그에 저장합니다.

## 로컬 콘텐츠와 AI

사용자가 저장한 영상, 자막, 메타데이터, 검색 색인과 AI 답변은 로컬 아카이브에
저장됩니다. AI 질문은 기본적으로 사용자의 컴퓨터에서 실행되는 Ollama 로컬 API로
전달되며 외부 AI 서비스로 전송되지 않습니다.

Ollama 모델 파일은 Ollama가 관리하는 로컬 저장소에 보관됩니다.

## 데이터 공유

앱은 사용자의 Google 데이터, 아카이브 자료 또는 AI 질문을 광고, 분석 또는 판매
목적으로 제3자에게 공유하지 않습니다. 사용자가 원본 링크를 열거나 자료를 직접
내보내는 경우에는 해당 사용자의 명시적인 동작에 따라 처리됩니다.

Google API에서 받은 데이터의 사용과 전송은
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)와
Limited Use 요구사항을 준수합니다.

## 데이터 삭제

앱에서 `계정 연결 해제`를 누르면 로컬 OAuth 토큰을 삭제하고 Google에 토큰
폐기를 요청하며, Google 권한으로 가져온 카탈로그 항목을 삭제합니다. 사용자는
[Google 계정 보안 설정](https://security.google.com/settings/security/permissions)에서도
앱 접근 권한을 철회할 수 있습니다. 사용자가 직접 가져온 로컬 아카이브 자료는
로컬 저장 폴더를 삭제하는 경우 제거됩니다.

## 보안

OAuth 토큰과 클라이언트 설정은 가능한 환경에서 소유자 전용 파일 권한으로
저장됩니다. 데스크톱 OAuth 인증은 PKCE와 state 검증을 사용합니다.

## 문의

- 운영자: 이태건
- 지원 이메일: [ltg0971@gmail.com](mailto:ltg0971@gmail.com)
- 홈페이지: <https://leetgeon.github.io/second-brain-archive>

앱은 YouTube API Services를 사용하며
[YouTube 이용약관](https://www.youtube.com/t/terms)과
[Google 개인정보처리방침](https://policies.google.com/privacy)을 함께
참조합니다.
