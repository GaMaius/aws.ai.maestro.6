"""모델 첫 호출 확인 (S1). 담당: PM. 규칙: .kiro/steering/agent-design.md 10번

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m scripts.ping_bedrock [서류 파일 경로 doc_type]

확인하는 것
    1. 인사 한 번: 응답 글자와 토큰 사용량
    2. structured_output 이 도는지 (Classification 모델)
    3. 도구 호출이 되는지 (today 도구)
    4. 서류 한 장 읽는 시간 (파일을 주면)
결과는 .kiro/specs/00-skeleton/design.md 의 'S1 결과' 표에 옮겨 적는다.
"""

import sys
import time

from strands import Agent, tool

from agent import make_model, text_of, today_kst
from tools.models import Classification


def _usage(result) -> dict:
    return dict(result.metrics.accumulated_usage)


def check_hello() -> None:
    agent = Agent(model=make_model(), callback_handler=None)
    started = time.perf_counter()
    result = agent("한국어로 한 문장만 인사해 줘.")
    print(f"[1] 인사: {text_of(result.message)!r}")
    print(f"    토큰: {_usage(result)}, 시간: {time.perf_counter() - started:.1f}초")


def check_structured_output() -> None:
    agent = Agent(model=make_model(), callback_handler=None)
    sample = "제목: PACKING LIST / 칸: Packing List No., N.W., G.W., Measurement"
    try:
        result = agent(f"아래 서류 요약을 보고 서류 종류를 골라라.\n{sample}", structured_output_model=Classification)
        print(f"[2] structured_output 동작함: {result.structured_output}")
    except Exception as exc:  # 모델이 지원하지 않으면 여기로 온다
        print(f"[2] structured_output 실패: {type(exc).__name__}: {exc}")


def check_tool_call() -> None:
    called: list[str] = []

    @tool
    def today() -> str:
        """한국 시간 기준 오늘 날짜를 돌려준다."""
        print("[tool] today 입력 없음")
        called.append("today")
        return today_kst()

    agent = Agent(model=make_model(), tools=[today], callback_handler=None)
    result = agent("today 도구로 오늘 날짜를 확인해서 알려줘.")
    print(f"[3] 도구 호출: {'됨' if called else '안 됨'}, 답: {text_of(result.message)!r}")


def check_read_time(path: str, doc_type: str) -> None:
    from pathlib import Path

    from tools.extract import read_document

    started = time.perf_counter()
    doc = read_document(Path(path).name, Path(path).read_bytes(), doc_type)
    print(f"[4] 서류 읽기 {time.perf_counter() - started:.1f}초, 품목 {len(doc.items)}행")
    print(doc.model_dump_json(indent=2, exclude_none=True))


def main(argv: list[str]) -> None:
    check_hello()
    check_structured_output()
    check_tool_call()
    if len(argv) >= 2:
        check_read_time(argv[0], argv[1])
    else:
        print("[4] 서류 파일을 주지 않아 읽기 시간은 건너뜀. 예: ... samples/invoice.pdf commercial_invoice")


if __name__ == "__main__":
    main(sys.argv[1:])
