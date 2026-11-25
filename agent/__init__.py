"""에이전트 공통 설정. 담당: 판독. 규칙: .kiro/steering/agent-design.md 10번

모델 ID는 코드에 적지 않고 환경 변수 MODEL_ID로 읽는다 (team.md).
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
REGION = os.environ.get("AWS_REGION", "ap-northeast-2")


def today_kst() -> str:
    """한국 시간 기준 오늘 날짜(YYYY-MM-DD). Lambda 시계는 UTC라 직접 계산한다."""
    return datetime.now(KST).date().isoformat()


def model_provider() -> str:
    """모델을 어디서 부르나. MODEL_PROVIDER=bedrock(기본, 원래 AWS 배포) | openai(OpenAI 호환 API: Groq·Ollama 등, 로컬 실행)."""
    return os.environ.get("MODEL_PROVIDER", "bedrock").strip().lower()


def make_model(read_timeout: int = 120, *, vision: bool = False):
    """모델 객체를 만든다.

    언제: Strands Agent를 만들 때.
    받는 것: read_timeout(읽기 타임아웃 초. 기본 120 = 서류 한 장 판독. 현황 Agent는 API Gateway 30초 때문에 짧게, #257),
      vision(그림을 넣는 호출인지. OpenAI 호환 모드에서 그림을 읽는 모델 VISION_MODEL_ID를 고른다).
      환경 변수 MODEL_ID(필수), MAX_TOKENS(기본 8000), AWS_REGION(기본 ap-northeast-2).
    반환: strands BedrockModel, MODEL_PROVIDER=openai면 strands OpenAIModel.
    temperature 등 샘플링 값은 넣지 않는다 (Claude 5.5 계열에서 오류, agent-design.md 10번).
    """
    if model_provider() == "openai":
        return _openai_model(read_timeout, vision=vision)

    from botocore.config import Config
    from strands.models import BedrockModel

    model_id = os.environ.get("MODEL_ID")
    if not model_id:
        raise RuntimeError("환경 변수 MODEL_ID가 없습니다. 예: export MODEL_ID=<global 추론 프로필 ID>")
    return BedrockModel(
        model_id=model_id,
        region_name=REGION,
        max_tokens=int(os.environ.get("MAX_TOKENS", "8000")),
        # 읽기 타임아웃은 서류 한 장 판독 시간을 고려해 넉넉히, 재시도는 1회
        boto_client_config=Config(read_timeout=read_timeout, connect_timeout=5, retries={"max_attempts": 2, "mode": "standard"}),
    )


OPENAI_BASE_URL = "https://api.groq.com/openai/v1"  # 기본은 Groq. Ollama는 http://localhost:11434/v1


def _openai_model(read_timeout: int, *, vision: bool):
    """OpenAI 호환 API(기본 Groq 무료 등급)로 부르는 모델 (로컬 실행, docs/REBUILD.md).

    환경 변수: OPENAI_API_KEY(또는 GROQ_API_KEY), OPENAI_BASE_URL(기본 Groq), MODEL_ID(글자 읽기·채팅),
    VISION_MODEL_ID(사진 서류를 읽을 때. 없으면 MODEL_ID), MAX_TOKENS(기본 8000).
    키는 코드·저장소에 적지 않는다. 로컬 실행 설정은 local/env.example 참고.
    """
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("환경 변수 GROQ_API_KEY(또는 OPENAI_API_KEY)가 없습니다. local/env.example을 보고 .env에 적으세요")
    model_id = (os.environ.get("VISION_MODEL_ID") if vision else None) or os.environ.get("MODEL_ID")
    if not model_id:
        raise RuntimeError("환경 변수 MODEL_ID가 없습니다. 예: MODEL_ID=openai/gpt-oss-120b")
    from strands.models.openai import OpenAIModel  # openai 패키지는 로컬 실행용(uv sync --group local)에만 있다

    return OpenAIModel(
        client_args={
            "api_key": api_key,
            "base_url": os.environ.get("OPENAI_BASE_URL", OPENAI_BASE_URL),
            "timeout": read_timeout,
            "max_retries": 1,
        },
        model_id=model_id,
        params={"max_tokens": int(os.environ.get("MAX_TOKENS", "8000"))},
    )


def text_of(message: dict) -> str:
    """응답 메시지에서 text 블록만 이어 붙인다. 위치(content[0])가 아니라 블록 종류로 읽는다."""
    return "".join(block["text"] for block in message.get("content", []) if "text" in block)
