"""현황 조회 Agent. 담당: 판독. 규칙: .kiro/steering/agent-design.md 9번, 형식: docs/schema.md (POST /chat)

작업: e2e-plan.md E5 (P1). 문서 처리 Agent와 시스템 프롬프트·도구 목록을 따로 둔다.
"""

from tools.models import ChatResponse
from tools.query import ShipmentStore


def answer(question: str, session_id: str, *, store: ShipmentStore) -> ChatResponse:
    """현황 질문에 답한다.

    언제: POST /chat.
    받는 것: question(사용자 질문), session_id, store(화물 기록).
    반환: ChatResponse. 모델은 질문을 ChatFilters로 바꾸기만 하고, 조회·건수는 query_shipments가 한다.
          답에는 조회 결과에 있는 건만 쓴다. 0건이면 0건과 쓴 조건을 보여 준다.
    """
    raise NotImplementedError("E5: 현황 조회 Agent (판독 담당)")
