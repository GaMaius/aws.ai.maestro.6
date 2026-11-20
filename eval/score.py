"""채점. 담당: 검증(코드), 정답지 CSV는 판독. 규칙: .kiro/steering/agent-design.md 11번, 형식: docs/schema.md 약속 3

작업: e2e-plan.md H1·H2. 저장된 판독(판독 캐시)으로 모델 호출 없이 다시 채점할 수 있어야 한다.
결과는 건수로 쓴다. 예: "심은 오류 20건 중 17건 탐지, 정상 10세트 중 오탐 0건".
"""

import csv
from pathlib import Path

from tools.models import Issue

EVAL_DIR = Path(__file__).parent


def load_answers(path: Path = EVAL_DIR / "answers.csv") -> list[dict[str, str]]:
    """정답지(약속 3)를 읽는다."""
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def score_detection(answers: list[dict[str, str]], issues_by_set: dict[str, list[Issue]], split: str) -> dict:
    """판정 채점: 탐지와 오탐.

    받는 것: 정답지 줄, 세트 ID → 그 세트의 issues, split(dev · test).
    반환: {"planted", "detected", "normal_sets", "false_positive_sets", "misses": [...]}.
    탐지는 심은 칸(doc, field)을 짚었을 때만 센다. 오탐은 정상 세트에서 센다.
    """
    raise NotImplementedError("H1: 판정 채점 (검증 담당)")


def score_fields(fields_csv: Path, docs_by_set: dict) -> dict:
    """읽기 채점: eval/fields.csv로 칸별 판독 정답 수."""
    raise NotImplementedError("H1: 읽기 채점 (검증 담당)")
