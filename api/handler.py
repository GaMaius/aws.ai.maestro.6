"""Lambda 진입점 (Function URL, 이벤트 형식 2.0). 담당: 서버. 형식: docs/schema.md 약속 2

뼈대 경로
    GET  /            → {"ok": true}            (S4 배포 확인)
    POST /jobs        → {"job_id"}              (S5, 안에서 끝까지 처리)
    GET  /jobs/{id}   → Job                     (S5)
나머지 경로(/uploads, /jobs/{id}/hs, /jobs/{id}/approve, /chat)는 501을 돌려준다. Spec 2·3에서 채운다.

환경 변수: JOBS_TABLE(team06-jobs), DOCS_BUCKET(team06-docs-...), MODEL_ID
"""

import base64
import json
import os
import re
import time
import uuid
from functools import cache

from tools.models import Job

ALLOWED_DOC_TYPES = {"commercial_invoice", "packing_list"}  # 뼈대 범위 (S2)
JOB_ID = re.compile(r"^job-[0-9a-f]{8}$")
KEY_PREFIX = "uploads/"


# ---------------------------------------------------------------------------
# AWS 자원 (테스트에서 바꿔 끼운다)
# ---------------------------------------------------------------------------
@cache
def _table():
    import boto3

    return boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])


@cache
def _s3():
    import boto3
    from botocore.config import Config

    return boto3.client("s3", config=Config(connect_timeout=5, read_timeout=5, retries={"max_attempts": 2}))


def fetch_object(key: str) -> bytes:
    """DOCS_BUCKET에서 파일을 받는다."""
    print(f"[tool] s3_get key={key}")
    return _s3().get_object(Bucket=os.environ["DOCS_BUCKET"], Key=key)["Body"].read()


def save_job(job: Job) -> None:
    """Job을 JSON 문자열 한 칸으로 저장한다 (float → Decimal 변환 문제를 피함)."""
    _table().put_item(
        Item={"job_id": job.job_id, "data": job.model_dump_json(by_alias=True), "updated_at": int(time.time())}
    )


def load_job(job_id: str) -> Job | None:
    item = _table().get_item(Key={"job_id": job_id}).get("Item")
    return Job.model_validate_json(item["data"]) if item else None


# ---------------------------------------------------------------------------
# 응답
# ---------------------------------------------------------------------------
def _response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def _error(status: int, message: str) -> dict:
    return _response(status, {"error": message})


def _body(event: dict):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw) if raw else {}


def _validate_files(body) -> tuple[list[dict] | None, str | None]:
    """POST /jobs 요청 검사. (files, 오류 메시지)"""
    files = body.get("files") if isinstance(body, dict) else None
    if not isinstance(files, list) or not files:
        return None, "files 목록이 비어 있습니다"
    from agent.document_agent import MAX_FILES

    if len(files) > MAX_FILES:
        return None, f"서류는 한 번에 {MAX_FILES}개까지입니다"
    clean = []
    for f in files:
        key = f.get("key") if isinstance(f, dict) else None
        doc_type = f.get("doc_type") if isinstance(f, dict) else None
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX) or ".." in key:
            return None, f"key는 '{KEY_PREFIX}'로 시작해야 합니다"
        if doc_type is None:
            return None, "뼈대에서는 doc_type이 필요합니다 (자동 분류는 Spec 1)"
        if doc_type not in ALLOWED_DOC_TYPES:
            return None, f"doc_type은 {sorted(ALLOWED_DOC_TYPES)} 중 하나입니다"
        clean.append({"key": key, "doc_type": doc_type})
    return clean, None


# ---------------------------------------------------------------------------
# 경로
# ---------------------------------------------------------------------------
def create_job(body) -> dict:
    files, problem = _validate_files(body)
    if problem:
        return _error(400, problem)
    from agent.document_agent import run_job

    job_id = f"job-{uuid.uuid4().hex[:8]}"
    save_job(Job(job_id=job_id, status="running"))
    started = time.perf_counter()
    try:
        job = run_job(job_id, files, fetch_object)
    except Exception as exc:  # 예상 못 한 오류도 작업 상태로 남긴다
        print(f"[error] job={job_id} {type(exc).__name__}: {exc}")
        job = Job(job_id=job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    print(f"[job] {job_id} status={job.status} {time.perf_counter() - started:.1f}초")
    save_job(job)
    return _response(200, {"job_id": job_id})


def get_job(job_id: str) -> dict:
    if not JOB_ID.match(job_id):
        return _error(404, "작업을 찾을 수 없습니다")
    job = load_job(job_id)
    if job is None:
        return _error(404, "작업을 찾을 수 없습니다")
    return _response(200, job.model_dump(mode="json", by_alias=True))


# 약속 2에 있지만 아직 없는 경로 → 작업 ID (e2e-plan.md). 만들면 여기서 지운다.
_PLANNED = {
    ("POST", "/uploads"): "F2",
    ("POST", "/jobs/{id}/hs"): "C3",
    ("POST", "/jobs/{id}/approve"): "D3",
    ("POST", "/chat"): "E5",
}


def _planned_route(method: str, path: str) -> str | None:
    parts = path.split("/")
    if len(parts) == 4 and parts[1] == "jobs":
        path = f"/jobs/{{id}}/{parts[3]}"
    return _PLANNED.get((method, path))


def lambda_handler(event, context):
    """Function URL 요청을 경로별로 나눈다."""
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method", "GET"), event.get("rawPath", "/").rstrip("/") or "/"
    print(f"[api] {method} {path}")
    try:
        if method == "GET" and path == "/":
            return _response(200, {"ok": True})
        if method == "POST" and path == "/jobs":
            return create_job(_body(event))
        if method == "GET" and path.startswith("/jobs/") and path.count("/") == 2:
            return get_job(path.split("/")[2])
        planned = _planned_route(method, path)
        if planned:
            return _error(501, f"아직 만들지 않은 경로입니다 ({planned}). 형식은 docs/schema.md 약속 2")
        return _error(404, "없는 경로입니다")
    except json.JSONDecodeError:
        return _error(400, "본문이 JSON이 아닙니다")
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}")
        return _error(500, "서버 오류")
