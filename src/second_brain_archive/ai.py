from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .archive import Archive, SearchHit
from .local_ai import DEFAULT_OLLAMA_MODEL


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[SearchHit]
    model: str


class OllamaAssistant:
    def __init__(
        self,
        archive: Archive,
        model: str = DEFAULT_OLLAMA_MODEL,
        base_url: str = "http://127.0.0.1:11434",
    ) -> None:
        self.archive = archive
        self.model = model
        self.base_url = base_url.rstrip("/")

    def ask(self, question: str, limit: int = 4) -> Answer:
        sources = self.archive.search(question, limit=limit)
        if not sources and self._is_archive_overview_question(question):
            sources = self.archive.recent_chunks(limit=limit)
        if not sources:
            return Answer(
                text="저장된 자료에서 이 질문과 관련된 근거를 찾지 못했습니다.",
                sources=[],
                model=self.model,
            )

        context_parts = []
        for index, hit in enumerate(sources, start=1):
            context_parts.append(
                f"[{index}] 자료: {hit.title}\n"
                f"시점: {hit.timestamp}\n"
                f"내용: {hit.text}"
            )
        context = "\n\n".join(context_parts)
        prompt = (
            "당신은 개인 콘텐츠 아카이브의 근거 중심 연구 도우미입니다.\n"
            "아래 검색 근거만 사용해 한국어로 답하세요.\n"
            "근거에 없는 내용은 추측하지 말고 부족하다고 명시하세요.\n"
            "실패 사례나 부정 표현을 해결책 또는 긍정 주장으로 바꾸지 마세요.\n"
            "모든 문단과 목록 항목 끝에 반드시 [1] 같은 출처 번호를 붙이세요.\n"
            "출처 번호가 없는 문장은 작성하지 마세요.\n"
            "질문하지 않은 실천 방법이나 조언을 추가하지 마세요.\n"
            "답변은 500자 이내로, 질문에 직접 답하는 결론과 근거에 명시된 "
            "보충 설명만 작성하세요.\n"
            "목록은 필요한 경우에만 최대 3개까지 사용하세요.\n"
            "중복하지 말고 마지막 문장을 완결하세요.\n\n"
            f"질문:\n{question}\n\n검색 근거:\n{context}"
        )
        if self.model.startswith("qwen3"):
            prompt = f"/no_think\n{prompt}"
        payload = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "최종 답변만 출력하세요. 분석 과정, 계획, 자기 대화, "
                            "질문 재진술은 절대 출력하지 마세요."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "think": False,
                "options": {"temperature": 0.2, "num_predict": 384},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Ollama returned HTTP {error.code}: {detail}"
            ) from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {error}") from error

        text = data.get("message", {}).get("content", "").strip()
        if "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        if not text:
            raise RuntimeError(f"Ollama returned an empty response: {data}")
        if not re.search(r"\[\d+\]", text):
            references = " ".join(
                f"[{index}]" for index in range(1, len(sources) + 1)
            )
            text = f"{text}\n\n참고 근거: {references}"
        return Answer(text=text, sources=sources, model=self.model)

    @staticmethod
    def _is_archive_overview_question(question: str) -> bool:
        normalized = " ".join(question.split())
        return any(
            phrase in normalized
            for phrase in (
                "아카이브",
                "저장한 자료",
                "저장된 자료",
                "전체 자료",
                "자료들이",
                "공통으로",
                "전반적으로",
            )
        )
