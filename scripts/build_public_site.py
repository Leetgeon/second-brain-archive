#!/usr/bin/env python3
from __future__ import annotations

import html
import sys
from pathlib import Path

from second_brain_archive.public_info import PublicInfo, public_info


STYLE = """
:root { color-scheme: light; font-family: Inter, system-ui, sans-serif; }
body { margin: 0; color: #17202a; background: #f5f1e8; line-height: 1.65; }
main { max-width: 780px; margin: 0 auto; padding: 72px 24px 96px; }
nav { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 64px; }
a { color: #235347; }
h1 { font-size: clamp(2.3rem, 7vw, 4.5rem); line-height: 1.05; }
h2 { margin-top: 2.4rem; }
.eyebrow { color: #96623b; letter-spacing: .14em; font-weight: 700; }
.card { margin-top: 32px; padding: 28px; background: #fffdf7; border-radius: 18px; }
footer { margin-top: 64px; color: #647067; }
"""


def page(info: PublicInfo, title: str, body: str) -> str:
    app_name = html.escape(info.app_name)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(title)} · {app_name}</title>
  <meta name="description" content="{app_name}는 YouTube 재생목록을 로컬 지식 카탈로그로 정리하는 데스크톱 앱입니다.">
  <style>{STYLE}</style>
</head>
<body><main>
  <nav>
    <a href="{html.escape(info.homepage_url)}">홈</a>
    <a href="{html.escape(info.privacy_url)}">개인정보처리방침</a>
    <a href="{html.escape(info.terms_url)}">이용약관</a>
  </nav>
  {body}
  <footer>
    운영자: {html.escape(info.operator_name)} ·
    <a href="mailto:{html.escape(info.support_email)}">{html.escape(info.support_email)}</a>
  </footer>
</main></body>
</html>
"""


def home(info: PublicInfo) -> str:
    return f"""
  <p class="eyebrow">LOCAL-FIRST KNOWLEDGE ARCHIVE</p>
  <h1>{html.escape(info.app_name)}</h1>
  <p>Google 계정의 YouTube 재생목록 제목, 항목 메타데이터와 원본 링크를 사용자의
  컴퓨터에만 저장하고 검색·Markdown 내보내기·로컬 AI 질문에 활용하는 데스크톱
  애플리케이션입니다.</p>
  <section class="card">
    <h2>Google 데이터 사용 범위</h2>
    <p><code>youtube.readonly</code> 권한은 사용자가 선택한 계정의 공개·일부공개·
    비공개 재생목록과 항목을 읽는 용도로만 사용합니다. YouTube 계정을 변경하지
    않으며 영상, 음성 또는 자막의 오프라인 사본을 저장하지 않습니다.</p>
    <p>OAuth 토큰과 가져온 메타데이터는 사용자의 컴퓨터에만 저장되며 운영자
    서버로 전송되지 않습니다.</p>
  </section>
"""


def privacy(info: PublicInfo) -> str:
    return """
  <p class="eyebrow">PRIVACY</p>
  <h1>개인정보처리방침</h1>
  <h2>Google 및 YouTube 데이터</h2>
  <p>앱은 사용자가 승인한 <code>youtube.readonly</code> 권한으로 YouTube 계정의
  재생목록과 재생목록 항목을 읽습니다. 계정이나 YouTube 콘텐츠를 수정하지
  않습니다. 영상, 음성 또는 자막의 오프라인 사본도 저장하지 않습니다.</p>
  <h2>저장과 공유</h2>
  <p>OAuth 토큰, 재생목록 메타데이터, 로컬 아카이브와 AI 질문은 사용자의
  컴퓨터에만 저장되며 운영자 서버, 광고 서비스 또는 데이터 판매자에게 전송되지
  않습니다.</p>
  <p>Google API에서 받은 데이터의 사용과 전송은
  <a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services User Data Policy</a>와
  Limited Use 요구사항을 준수합니다.</p>
  <h2>삭제와 권한 철회</h2>
  <p>앱에서 계정 연결을 해제하면 로컬 OAuth 토큰을 삭제하고 Google에 토큰 폐기를
  요청하며, Google 권한으로 가져온 카탈로그 항목을 삭제합니다.
  <a href="https://security.google.com/settings/security/permissions">Google 계정 보안 설정</a>에서도
  언제든 접근 권한을 철회할 수 있습니다.</p>
"""


def terms(info: PublicInfo) -> str:
    return f"""
  <p class="eyebrow">TERMS</p>
  <h1>이용약관</h1>
  <h2>YouTube 서비스</h2>
  <p>Google 계정 연결 기능은 YouTube API Services를 사용합니다. 사용자는
  <a href="https://www.youtube.com/t/terms">YouTube 이용약관</a>과
  <a href="https://policies.google.com/privacy">Google 개인정보처리방침</a>의
  적용을 받습니다.</p>
  <h2>사용 범위</h2>
  <p>공개 배포본은 재생목록 제목, 항목과 원본 링크를 로컬 카탈로그에 표시합니다.
  YouTube 영상의 다운로드, 백업 또는 오프라인 재생 기능은 제공하지 않습니다.</p>
  <h2>사용자 자료</h2>
  <p>사용자는 자신이 권리를 보유하거나 적법하게 사용할 수 있는 로컬 파일만
  가져와야 합니다. 앱은 사용자가 제공한 자료의 권리를 취득하지 않습니다.</p>
  <h2>준거법</h2>
  <p>본 약관은 {html.escape(info.jurisdiction)}의 법률을 따릅니다.</p>
"""


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "site-dist")
    info = public_info()
    errors = info.validation_errors()
    if errors:
        raise SystemExit("공개 사이트 설정이 누락됐습니다: " + ", ".join(errors))

    pages = {
        "index.html": page(info, "홈", home(info)),
        "privacy/index.html": page(info, "개인정보처리방침", privacy(info)),
        "terms/index.html": page(info, "이용약관", terms(info)),
    }
    for relative, contents in pages.items():
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
