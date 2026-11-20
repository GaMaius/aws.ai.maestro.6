"""reread_field. 담당: 판독. 규칙: .kiro/steering/agent-design.md 4번, 형식: docs/schema.md

작업: e2e-plan.md B8 (P1).
"""

from tools.extract import ModelReader
from tools.models import ExtractedDocument, Issue, OcrResult, RereadResult


def reread_field(
    doc: ExtractedDocument,
    field: str,
    data: bytes,
    *,
    ocr: OcrResult | None = None,
    reader: ModelReader | None = None,
) -> RereadResult:
    """불일치에 걸린 칸 하나를 첫 판독과 다른 방법으로 다시 확인한다.

    언제: cross_check가 불일치를 낸 칸마다. 서류 전체를 다시 읽지 않는다.
    받는 것: doc(첫 판독 결과), field(칸 경로, 예 'items[0].gross_kg'), data(원본 파일),
             ocr(저장해 둔 Textract 결과, 사진·스캔본일 때), reader(테스트용 가짜 모델).
    반환: RereadResult. 방법 순서: 텍스트 PDF면 pdf_text → OCR이 있으면 textract → 둘 다 없으면 model_reread.
    """
    print(f"[tool] reread_field doc={doc.doc_type} field={field}")
    raise NotImplementedError("B8: 다시 확인 (판독 담당)")


def apply_rereads(issues: list[Issue], rereads: list[RereadResult]) -> list[Issue]:
    """다시 확인 결과를 issues에 반영한다.

    언제: reread_field를 모두 부른 뒤.
    받는 것: cross_check가 낸 issues, reread_field 결과 목록.
    반환: 새 issues. 두 근거가 같으면 불일치 그대로(checked_by 채움), 다르면 '확인 필요(읽기 오류 의심)'로 내린다.
    """
    raise NotImplementedError("B8: 다시 확인 반영 (판독 담당)")
