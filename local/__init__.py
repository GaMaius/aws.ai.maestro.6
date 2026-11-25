"""로컬 실행 (AWS 없이). 담당: 개인 포크 재구축 (docs/REBUILD.md M2).

    uv sync --group local
    uv run uvicorn server.app:app --port 8000

install() 한 번으로
1. 저장소 맨 위 .env 를 읽어 환경 변수로 넣고 (이미 있는 값은 그대로), 로컬 기본값을 채운다
2. boto3 가 DynamoDB·S3·Lambda 대신 local.aws 의 대체물을 돌려주게 하고
3. 처리 worker 의 OCR 을 local.ocr 로 바꾸고
4. 화물 기록 테이블이 비었으면 시드(infra/seed_shipments.py)를 넣는다.
원래 AWS 코드 경로(api/, tools/, agent/)는 고치지 않는다.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULTS = {
    "JOBS_TABLE": "team06-jobs",
    "HS_HISTORY_TABLE": "team06-hs-history",
    "WMS_TABLE": "team06-wms",
    "SHIPMENTS_TABLE": "team06-shipments",
    "CHAT_TABLE": "team06-chat",
    "DOCS_BUCKET": "local-docs",
    "WORKER_FUNCTION": "local-worker",
    "MODEL_PROVIDER": "openai",
    "MODEL_ID": "openai/gpt-oss-120b",
    "VISION_MODEL_ID": "qwen/qwen3.8-27b",
    "MAX_TOKENS": "4000",
    "AWS_REGION": "ap-northeast-2",
    # 로컬에는 AWS 자격 증명이 없다. boto3 가 자격 증명을 찾다가 느려지지 않게 가짜 값을 둔다 (실제로 AWS 를 부르지 않는다)
    "AWS_ACCESS_KEY_ID": "local",
    "AWS_SECRET_ACCESS_KEY": "local",
}

_installed = False


def data_dir() -> Path:
    """로컬 저장 폴더 (SQLite·업로드 파일). LOCAL_DATA_DIR 로 바꿀 수 있다. 저장소에는 올리지 않는다 (.gitignore)."""
    return Path(os.environ.get("LOCAL_DATA_DIR") or ROOT / ".local-data")


def load_env_file(path: Path) -> None:
    """KEY=VALUE 줄만 읽는 간단한 .env 읽기. 이미 있는 환경 변수는 덮어쓰지 않는다."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def install() -> None:
    global _installed
    if _installed:
        return
    load_env_file(ROOT / ".env")
    for key, value in DEFAULTS.items():
        os.environ.setdefault(key, value)

    import boto3

    from local.aws import LocalDatabase, LocalDynamoResource, LocalLambda, LocalS3

    base = data_dir()
    dynamo = LocalDynamoResource(LocalDatabase(base / "local.db"))
    s3 = LocalS3(base / "s3")
    lam = LocalLambda()
    real_client, real_resource = boto3.client, boto3.resource

    def client(service_name, *args, **kwargs):
        if service_name == "s3":
            return s3
        if service_name == "lambda":
            return lam
        if service_name in ("textract", "sesv2", "bedrock-runtime"):
            raise RuntimeError(f"로컬 실행에서는 {service_name}을 부르지 않습니다 (local/README.md)")
        return real_client(service_name, *args, **kwargs)

    def resource(service_name, *args, **kwargs):
        if service_name == "dynamodb":
            return dynamo
        return real_resource(service_name, *args, **kwargs)

    boto3.client, boto3.resource = client, resource

    from api import worker
    from local.ocr import local_ocr_document

    worker.ocr_document = local_ocr_document
    seed_shipments(dynamo.Table(os.environ["SHIPMENTS_TABLE"]))
    _installed = True
    print(f"[local] 로컬 실행 준비: 저장 {base}, 모델 {os.environ['MODEL_PROVIDER']}:{os.environ['MODEL_ID']}")


def seed_shipments(table) -> None:
    """화물 기록이 비었으면 시드를 오늘 날짜 기준으로 옮겨 넣는다 (현황 조회·대시보드용)."""
    if table.scan()["Items"]:
        return
    import sys

    sys.path.insert(0, str(ROOT))
    from infra.seed_shipments import load, seed_file, to_item

    rows = load(seed_file())
    for shipment in rows:
        table.put_item(Item=to_item(shipment))
    print(f"[local] 화물 기록 시드 {len(rows)}건")
