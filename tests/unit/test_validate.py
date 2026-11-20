"""cross_check(X-WT-01 총중량) 단위 테스트. 가짜 추출 결과를 쓴다."""

from tools.models import Cell, ExtractedDocument, ExtractedItem
from tools.validate import cross_check


def doc(doc_type, total_raw=None, total=None, items=None, unreadable=None):
    total_cell = None
    if total_raw is not None or unreadable is not None:
        total_cell = Cell(raw=total_raw, value=total, unreadable=unreadable)
    return ExtractedDocument(
        doc_type=doc_type,
        file=f"uploads/s/{doc_type}.pdf",
        items=items or [],
        total_gross_kg=total_cell,
    )


def test_match_gives_no_issue():
    docs = [doc("commercial_invoice", "6,520.00 KGS", 6520.0), doc("packing_list", "6,520 KG", 6520.0)]
    assert cross_check(docs) == []


def test_mismatch_two_docs():
    docs = [doc("commercial_invoice", "6,250.00 KGS", 6250.0), doc("packing_list", "6,520.00 KGS", 6520.0)]
    [issue] = cross_check(docs)
    assert issue.rule_id == "X-WT-01" and issue.grade == "불일치"
    assert issue.suspect is None
    assert issue.evidence == "상업송장 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다."
    assert [(c.doc, c.raw) for c in issue.cells] == [
        ("commercial_invoice", "6,250.00 KGS"),
        ("packing_list", "6,520.00 KGS"),
    ]


def test_unreadable_is_not_counted_as_match():
    docs = [doc("commercial_invoice", "6,520.00 KGS", 6520.0), doc("packing_list", unreadable="흐림")]
    [issue] = cross_check(docs)
    assert issue.grade == "확인 필요"
    assert issue.cells[0].doc == "packing_list"
    assert issue.evidence == "포장명세서 총중량을 읽지 못했습니다(흐림)."


def test_within_tolerance_is_note():
    docs = [doc("commercial_invoice", "6,520.00", 6520.0), doc("packing_list", "6,520.05", 6520.05)]
    [issue] = cross_check(docs)
    assert issue.grade == "참고"


def test_majority_picks_suspect_with_three_docs():
    docs = [
        doc("commercial_invoice", "6,250", 6250.0),
        doc("bill_of_lading", "6,250", 6250.0),
        doc("packing_list", "6,520", 6520.0),
    ]
    [issue] = cross_check(docs)
    assert issue.grade == "불일치" and issue.suspect == "packing_list"
    assert issue.evidence == "포장명세서 총중량 6,520kg과 상업송장·선하증권 6,250kg이 다릅니다."


def test_item_sum_used_when_no_total_cell():
    items = [
        ExtractedItem(line=1, gross_kg=Cell(raw="3,000 KGS", value=3000.0)),
        ExtractedItem(line=2, gross_kg=Cell(raw="3,520 KGS", value=3520.0)),
    ]
    docs = [doc("commercial_invoice", "6,520", 6520.0), doc("packing_list", items=items)]
    assert cross_check(docs) == []


def test_item_row_unreadable_means_check_needed():
    items = [
        ExtractedItem(line=1, gross_kg=Cell(raw="3,000 KGS", value=3000.0)),
        ExtractedItem(line=2, gross_kg=Cell(raw=None, value=None, unreadable="가려짐")),
    ]
    docs = [doc("commercial_invoice", "6,520", 6520.0), doc("packing_list", items=items)]
    [issue] = cross_check(docs)
    assert issue.grade == "확인 필요"
    assert issue.evidence == "포장명세서 총중량을 읽지 못했습니다(가려짐)."
    assert issue.cells[0].field == "items[1].gross_kg"


def test_single_doc_has_nothing_to_compare():
    assert cross_check([doc("packing_list", "6,520", 6520.0)]) == []
