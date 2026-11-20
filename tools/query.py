"""query_shipments. 담당: 판독. 규칙: .kiro/steering/agent-design.md 9번, 형식: docs/schema.md

작업: e2e-plan.md E4 (P1). 통관 지연 기준은 검증 담당이 docs/schema.md에 정한다 (E1).
"""

from datetime import date
from typing import Protocol

from tools.models import ChatFilters, PeriodResolved, QueryResult, Shipment


class ShipmentStore(Protocol):
    """화물 기록(team06-shipments). 구현: api/ (DynamoDB), 테스트: 메모리 목록."""

    def all(self) -> list[Shipment]: ...


def resolve_period(filters: ChatFilters, today: date) -> PeriodResolved | None:
    """기간 조건을 한국 시간 기준 날짜 범위로 바꾼다. 모델이 날짜를 계산하지 않는다.

    받는 것: filters(period, range면 date_from·date_to), today(한국 시간 오늘. agent.today_kst()).
    반환: PeriodResolved. 기간 조건이 없으면 None.
    """
    raise NotImplementedError("E4: 기간 계산 (판독 담당)")


def query_shipments(filters: ChatFilters, *, store: ShipmentStore, today: date) -> QueryResult:
    """조회 조건으로 화물 기록을 찾고 센다. 조회·집계·정렬은 코드가 한다.

    언제: 현황 조회 Agent가 질문을 조건으로 바꾼 뒤.
    받는 것: filters, store, today(한국 시간).
    반환: QueryResult. 건수는 코드가 센 값, 쓴 상태 규칙 설명 포함.
    """
    print(f"[tool] query_shipments filters={filters.model_dump(exclude_none=True)}")
    raise NotImplementedError("E4: 현황 조회 (판독 담당)")
