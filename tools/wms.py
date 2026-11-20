"""push_to_wms (에이전트 도구 아님). 담당: 서버. 규칙: .kiro/steering/agent-design.md 8번, 형식: docs/schema.md

에이전트 도구 목록에 넣지 않는다. 외부 시스템에 쓰는 일은 코드만 한다.
작업: e2e-plan.md D1·D2·D3 (P1). 실제 WMS로 바꿀 때는 WmsAdapter 구현만 바꾼다.
"""

from typing import Protocol

from tools.models import JobResult, WmsBy, WmsRecord, WmsState


class WmsAdapter(Protocol):
    """WMS 하나. 가상 WMS(DynamoDB)든 실제 시스템이든 이 모양만 맞추면 된다."""

    def register(self, record: WmsRecord) -> str:
        """등록하고 wms_id를 돌려준다. 같은 idempotency_key면 이미 있는 wms_id를 돌려준다."""
        ...


class ApprovalRefused(Exception):
    """불일치가 남아 승인해도 등록하지 않음 (API는 409)."""


def can_auto_register(result: JobResult) -> bool:
    """자동 등록 조건: 불일치·확인 필요가 하나도 없고 모든 품목의 HS가 확정됨."""
    raise NotImplementedError("D2: 자동 등록 조건 (서버 담당)")


def push_to_wms(record: WmsRecord, *, adapter: WmsAdapter) -> WmsState:
    """가상 WMS에 한 건 등록한다.

    언제: finish_report 직후 can_auto_register가 참이면(by=auto), 또는 사람이 승인하면(by=human).
    받는 것: record(멱등 키 포함), adapter.
    반환: WmsState(status='등록됨', by, wms_id).
    """
    print(f"[tool] push_to_wms key={record.idempotency_key} by={record.by}")
    raise NotImplementedError("D1: 가상 WMS 등록 (서버 담당)")


def approve(result: JobResult, by: WmsBy = "human") -> None:
    """사람 승인 전 검사. 불일치가 남았으면 ApprovalRefused."""
    raise NotImplementedError("D3: 승인 검사 (서버 담당)")
