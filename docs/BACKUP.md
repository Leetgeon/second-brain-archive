# 백업과 복구

원본 영상은 다시 구하지 못할 수 있으므로 데이터베이스만 백업해서는 충분하지 않다.
`data/` 전체를 백업 대상으로 사용한다.

## 외장 디스크 백업

```bash
./scripts/backup.sh "/Volumes/My Archive"
```

명령은 날짜가 포함된 `second-brain-YYYYMMDD-HHMMSS/data/` 폴더를 만든다.
Google OAuth 클라이언트와 토큰이 있는 `data/secrets/`는 보안상 자동 백업에서
제외된다. 새 Mac에서는 YouTube 계정을 다시 연결한다.

## 무결성 확인

```bash
PYTHONPATH=src /Users/mac/.pyenv/versions/3.12.13/bin/python \
  -m second_brain_archive --root data verify
```

SQLite 자체 검사와 모든 원본 파일의 SHA-256을 다시 계산한다.

## 복구

1. 백업의 `data/` 폴더를 프로젝트 루트에 복사한다.
2. `second-brain --root data verify`를 실행한다.
3. `./scripts/run.sh`로 대시보드를 연다.

권장 방식은 작업용 원본 1개, 외장 디스크 1개, 다른 물리적 위치나 신뢰할 수 있는
클라우드 1개를 두는 3-2-1 백업이다.
