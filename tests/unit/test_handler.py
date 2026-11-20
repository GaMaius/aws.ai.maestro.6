"""api/handler.py 단위 테스트. DynamoDB·S3·Bedrock은 가짜로 바꾼다."""

import json

import pytest

import api.handler as handler
import tools.extract as extract
from tools.models import Job, RawDocument

TOTALS = {"invoice.pdf": "6,250.00 KGS", "packing_list.pdf": "6,520.00 KGS", "pl_ok.pdf": "6,250 KG"}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item):
        self.items[Item["job_id"]] = Item

    def get_item(self, Key):
        item = self.items.get(Key["job_id"])
        return {"Item": item} if item else {}


@pytest.fixture
def fakes(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(handler, "_table", lambda: table)
    # S3 대신 키 이름을 바이트로 돌려준다
    monkeypatch.setattr(handler, "fetch_object", lambda key: key.encode())

    def fake_reader(blocks, prompt):
        key = blocks[0]["document"]["source"]["bytes"].decode()
        name = key.rsplit("/", 1)[-1]
        if name == "broken.pdf":
            raise RuntimeError("모델 오류")
        return RawDocument.model_validate({"total_gross_kg": {"raw": TOTALS[name]}})

    monkeypatch.setattr(extract, "_strands_reader", fake_reader)
    return table


def call(method, path, body=None):
    event = {"requestContext": {"http": {"method": method}}, "rawPath": path}
    if body is not None:
        event["body"] = json.dumps(body)
    res = handler.lambda_handler(event, None)
    return res["statusCode"], json.loads(res["body"])


def files(*names):
    types = {"invoice.pdf": "commercial_invoice"}
    return {"files": [{"key": f"uploads/s1/{n}", "doc_type": types.get(n, "packing_list")} for n in names]}


def test_health():
    assert call("GET", "/") == (200, {"ok": True})


def test_post_then_get_shows_mismatch(fakes):
    status, body = call("POST", "/jobs", files("invoice.pdf", "packing_list.pdf"))
    assert status == 200
    status, job = call("GET", f"/jobs/{body['job_id']}")
    assert status == 200
    Job.model_validate(job)  # 약속 2 형식
    assert job["status"] == "waiting_approval"
    assert [s["tool"] for s in job["steps"]] == ["read_document", "read_document", "cross_check"]
    [issue] = job["result"]["issues"]
    assert issue["grade"] == "불일치" and issue["rule_id"] == "X-WT-01"


def test_matching_docs_are_done(fakes):
    _, body = call("POST", "/jobs", files("invoice.pdf", "pl_ok.pdf"))
    _, job = call("GET", f"/jobs/{body['job_id']}")
    assert job["status"] == "done" and job["result"]["issues"] == []


def test_read_failure_is_check_needed(fakes):
    _, body = call("POST", "/jobs", files("invoice.pdf", "broken.pdf"))
    _, job = call("GET", f"/jobs/{body['job_id']}")
    assert job["status"] == "waiting_approval"
    assert job["result"]["issues"][0]["rule_id"] == "READ-FAIL"
    assert job["steps"][1]["ok"] is False


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"files": []},
        {"files": [{"key": "secret/x.pdf", "doc_type": "packing_list"}]},
        {"files": [{"key": "uploads/../x.pdf", "doc_type": "packing_list"}]},
        {"files": [{"key": "uploads/x.pdf", "doc_type": None}]},
        {"files": [{"key": "uploads/x.pdf", "doc_type": "bill_of_lading"}]},
    ],
)
def test_bad_requests_are_400(fakes, body):
    assert call("POST", "/jobs", body)[0] == 400


def test_unknown_job_and_path_are_404(fakes):
    assert call("GET", "/jobs/job-00000000")[0] == 404
    assert call("GET", "/jobs/../../etc")[0] == 404
    assert call("GET", "/nothing")[0] == 404


@pytest.mark.parametrize(
    "path", ["/uploads", "/jobs/job-00000000/hs", "/jobs/job-00000000/approve", "/chat"]
)
def test_planned_routes_are_501(fakes, path):
    """약속 2의 경로가 모두 자리를 갖고 있다. 만들면 이 목록에서 뺀다."""
    assert call("POST", path, {})[0] == 501
