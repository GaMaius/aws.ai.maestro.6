"""서류 교차 검증. 담당: 검증. 규칙: .kiro/steering/agent-design.md 3·5번, 형식: docs/schema.md 약속 2

뼈대(S3)에는 규칙 하나(X-WT-01, 서류 전체 총중량)만 있다. 규칙 문장틀과 허용 오차는 tools/rules/rules.csv.
"""

import csv
from collections import Counter
from functools import cache
from pathlib import Path

from tools.models import DOC_TYPE_KO, ExtractedDocument, Grade, Issue, IssueCell

RULES_CSV = Path(__file__).parent / "rules" / "rules.csv"
_EPS = 1e-9


@cache
def load_rules() -> dict[tuple[str, str], dict[str, str]]:
    """rules.csv를 (rule_id, 등급) → 행으로 읽는다."""
    with RULES_CSV.open(encoding="utf-8", newline="") as fh:
        return {(row["rule_id"], row["grade"]): row for row in csv.DictReader(fh)}


def _rule(rule_id: str, grade: Grade) -> dict[str, str]:
    return load_rules()[(rule_id, grade)]


def _fmt(value: float) -> str:
    """6250.0 → '6,250', 6250.25 → '6,250.25'."""
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _total_gross(doc: ExtractedDocument) -> tuple[float | None, str, str | None, str | None]:
    """서류 전체 총중량. (값, 칸 경로, raw, 못 구한 이유)

    합계 칸을 먼저 쓰고, 없거나 못 읽었으면 행별 총중량을 코드가 더한다.
    행 하나라도 못 읽었으면 값은 None.
    """
    total = doc.total_gross_kg
    if total is not None and isinstance(total.value, (int, float)):
        return float(total.value), "total_gross_kg", total.raw, None
    cells = [item.gross_kg for item in doc.items]
    if cells and all(c is not None and isinstance(c.value, (int, float)) for c in cells):
        raw = " + ".join(c.raw or "" for c in cells)
        return round(sum(float(c.value) for c in cells), 3), "items[*].gross_kg", raw, None
    # 못 구한 이유: 합계 칸 → 행 순서로, 값을 못 구한 첫 칸의 이유
    paths = ["total_gross_kg", *(f"items[{i}].gross_kg" for i in range(len(cells)))]
    for path, cell in zip(paths, [total, *cells]):
        if cell is None or isinstance(cell.value, (int, float)):
            continue
        if cell.unreadable:
            return None, path, cell.raw, cell.unreadable
        if cell.raw is not None:
            return None, path, cell.raw, "숫자로 풀 수 없음"
    return None, "total_gross_kg", None, "칸 없음"


def _check_total_gross(docs: list[ExtractedDocument]) -> list[Issue]:
    rule_id = "X-WT-01"
    base = _rule(rule_id, "불일치")
    targets = set(base["target"].split(":")[0].split("|"))
    tol = float(base["tolerance"])
    docs = [d for d in docs if d.doc_type in targets]
    if len(docs) < 2:
        return []  # 비교할 상대가 없음

    issues: list[Issue] = []
    readable: list[tuple[ExtractedDocument, float, IssueCell]] = []
    for doc in docs:
        value, field, raw, reason = _total_gross(doc)
        cell = IssueCell(doc=doc.doc_type, field=field, raw=raw)
        if value is None:
            text = _rule(rule_id, "확인 필요")["template"].format(doc=DOC_TYPE_KO[doc.doc_type], reason=reason)
            issues.append(Issue(rule_id=rule_id, grade="확인 필요", cells=[cell], evidence=text))
        else:
            readable.append((doc, value, cell))
    if len(readable) < 2:
        return issues

    values = [v for _, v, _ in readable]
    spread = max(values) - min(values)
    if spread <= _EPS:
        return issues  # 일치
    cells = [c for _, _, c in readable]
    grade: Grade = "참고" if spread <= tol + _EPS else "불일치"

    # 다수결: 셋 이상이고 한 서류만 다르면 그 서류를 짚는다
    suspect = None
    counts = Counter(round(v, 3) for v in values)
    major_value, major_count = counts.most_common(1)[0]
    if len(readable) >= 3 and major_count == len(readable) - 1:
        odd = next((d, v) for d, v, _ in readable if round(v, 3) != major_value)
        suspect = odd[0].doc_type
        a_doc, a_val = DOC_TYPE_KO[odd[0].doc_type], odd[1]
        b_doc = "·".join(DOC_TYPE_KO[d.doc_type] for d, v, _ in readable if round(v, 3) == major_value)
        b_val = major_value
    else:
        first_doc, first_val, _ = readable[0]
        other_doc, other_val, _ = next(r for r in readable[1:] if abs(r[1] - first_val) > _EPS)
        a_doc, a_val, b_doc, b_val = DOC_TYPE_KO[first_doc.doc_type], first_val, DOC_TYPE_KO[other_doc.doc_type], other_val

    text = _rule(rule_id, grade)["template"].format(
        a_doc=a_doc, a_val=_fmt(a_val), b_doc=b_doc, b_val=_fmt(b_val), tol=_fmt(tol)
    )
    issues.append(Issue(rule_id=rule_id, grade=grade, cells=cells, suspect=suspect, evidence=text))
    return issues


def cross_check(docs: list[ExtractedDocument]) -> list[Issue]:
    """읽은 서류끼리 대조해 문제 목록을 돌려준다.

    언제: 서류를 모두 읽은 뒤, 그리고 다시 읽은 뒤마다.
    받는 것: read_document 결과 목록 (약속 1).
    반환: Issue 목록. 문제가 없으면 빈 목록. 못 읽은 값은 일치로 세지 않고 '확인 필요'로 낸다.
    """
    print(f"[tool] cross_check docs={[d.doc_type for d in docs]}")
    return _check_total_gross(docs)
