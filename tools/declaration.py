"""draft_declaration. 담당: 검증. 규칙: .kiro/steering/agent-design.md 7번, 형식: docs/schema.md

작업: e2e-plan.md C4·C5 (P1). 칸 목록과 출처는 docs/schema.md에 먼저 적고 여기 표로 옮긴다.
"""

from tools.models import DeclarationDraft, ExtractedDocument, HSResult, Issue

# (신고서 칸 이름, 출처 "서류.칸") 목록. C4에서 채운다. 예: ("품명", "commercial_invoice.items[0].name")
DECLARATION_FIELDS: list[tuple[str, str]] = []

DRAFT_NOTICE = "사람 검토 전 초안"


def draft_declaration(docs: list[ExtractedDocument], issues: list[Issue], hs: list[HSResult]) -> DeclarationDraft:
    """신고서 초안을 코드로 채운다. 모델은 쓰지 않는다.

    언제: HS 결과가 나온 뒤, 그리고 사람이 HS를 고른 뒤 다시.
    받는 것: 읽은 서류, 남은 문제, 품목별 HS 결과.
    반환: DeclarationDraft. 문제가 남은 칸과 확정 안 된 HS 칸은 비우고 blank_fields에 적는다.
    """
    print(f"[tool] draft_declaration docs={[d.doc_type for d in docs]} issues={len(issues)}")
    raise NotImplementedError("C5: 신고서 초안 (검증 담당)")
