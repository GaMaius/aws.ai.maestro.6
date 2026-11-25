"""포트폴리오 데모(정적 사이트)가 내려받기 링크로 주는 파일을 만든다.

원래 서비스에서는 서버(api/handler.py)가 부를 때마다 만들어 주는 문서들이다.
데모는 서버가 없으므로, 화면 예시 작업(docs/examples/job_waiting_approval.json)으로 같은 코드를 한 번 돌려
결과 파일을 web/public/demo/ 에 저장해 둔다. 모델·AWS 호출은 없다.

    uv run python scripts/build_demo_assets.py

만드는 파일
- notice.html, notice.md : 불일치 통지 문서 (docs/examples/notice.json 그대로)
- hs-request.pdf          : HS 확인 요청서 (tools/hs_request.py)
- certificate.pdf         : 검수 완료서 (tools/certificate.py). 예시 작업을 '데모 검수자'가 승인한 것으로 놓고 만든다
"""
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import certificate, hs_request  # noqa: E402
from tools.models import ExtractedDocument, Job  # noqa: E402

EXAMPLES = ROOT / "docs" / "examples"
OUT = ROOT / "web" / "public" / "demo"
KST_NOW = datetime.fromisoformat("2026-11-21T10:00:00+09:00")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    notice = json.loads((EXAMPLES / "notice.json").read_text(encoding="utf-8"))
    (OUT / "notice.html").write_text(notice["html"], encoding="utf-8")
    (OUT / "notice.md").write_text(notice["markdown"], encoding="utf-8")

    job = Job.model_validate_json((EXAMPLES / "job_waiting_approval.json").read_text(encoding="utf-8"))
    docs = [ExtractedDocument.model_validate_json((EXAMPLES / "extract_packing_list.json").read_text(encoding="utf-8"))]

    hs_request.check_requestable(job)
    (OUT / "hs-request.pdf").write_bytes(hs_request.make_hs_request(job, docs, now=KST_NOW))

    approved = job.model_copy(deep=True)
    wms = approved.result.wms
    wms.status = "등록됨"
    wms.by = "human"
    wms.wms_id = "WMS-DEMO-0001"
    wms.approver = "데모 검수자"
    wms.approved_at = KST_NOW.isoformat(timespec="seconds")
    if any(i.grade == "불일치" for i in approved.result.issues):
        wms.override_reason = "데모: 판독 오류로 확인함"
    certificate.check_issuable(approved)
    (OUT / "certificate.pdf").write_bytes(certificate.make_certificate(approved, docs))

    for p in sorted(OUT.iterdir()):
        print(f"{p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
