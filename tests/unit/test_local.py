"""로컬 실행 대체물 (local/, docs/REBUILD.md M2). AWS·모델·네트워크를 부르지 않는다.

local.install() 은 boto3 를 프로세스 전체에서 바꾸므로 여기서는 부르지 않고, 대체물 클래스만 직접 시험한다.
"""

import base64
import json
from pathlib import Path

import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from local.aws import LocalDatabase, LocalLambda, LocalS3, LocalTable, key_names
from local.http import from_result, to_event
from local.ocr import local_ocr_document, pdf_text_lines

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_PDF = ROOT / "samples" / "dev" / "D001" / "doc_a.pdf"


@pytest.fixture
def db(tmp_path):
    return LocalDatabase(tmp_path / "local.db")


def test_key_names_follow_infra_tables():
    assert key_names("team06-jobs") == ("job_id",)
    assert key_names("team06-chat") == ("session_id", "ts")
    with pytest.raises(ValueError):
        key_names("team06-unknown")


def test_table_put_get_and_conditions(db):
    wms = LocalTable(db, "team06-wms")
    wms.put_item(Item={"idempotency_key": "BL1#job-1", "wms_id": "W1"}, ConditionExpression="attribute_not_exists(idempotency_key)")
    assert wms.get_item(Key={"idempotency_key": "BL1#job-1"})["Item"]["wms_id"] == "W1"
    with pytest.raises(ClientError) as exc:
        wms.put_item(Item={"idempotency_key": "BL1#job-1", "wms_id": "W2"}, ConditionExpression="attribute_not_exists(idempotency_key)")
    assert exc.value.response["Error"]["Code"] == "ConditionalCheckFailedException"
    assert wms.get_item(Key={"idempotency_key": "nope"}) == {}


def test_shipment_condition_allows_overwrite_only_with_job(db):
    ships = LocalTable(db, "team06-shipments")
    cond = "attribute_not_exists(bl_no) OR attribute_exists(job_id)"
    ships.put_item(Item={"bl_no": "B1", "status": "seed"}, ConditionExpression=cond)  # 없던 줄
    with pytest.raises(ClientError):
        ships.put_item(Item={"bl_no": "B1", "status": "x"}, ConditionExpression=cond)  # 시드 줄은 덮지 않는다
    ships.put_item(Item={"bl_no": "B2", "job_id": "job-1"})
    ships.put_item(Item={"bl_no": "B2", "job_id": "job-2"}, ConditionExpression=cond)  # 작업이 쓴 줄은 덮는다
    assert ships.get_item(Key={"bl_no": "B2"})["Item"]["job_id"] == "job-2"


def test_scan_begins_with_and_query_order(db):
    wms = LocalTable(db, "team06-wms")
    for key in ("BL1#a", "BL1#b", "BL2#c"):
        wms.put_item(Item={"idempotency_key": key, "wms_id": key})
    page = wms.scan(FilterExpression="begins_with(idempotency_key, :prefix)", ExpressionAttributeValues={":prefix": "BL1#"})
    assert sorted(i["idempotency_key"] for i in page["Items"]) == ["BL1#a", "BL1#b"]
    assert "LastEvaluatedKey" not in page

    chat = LocalTable(db, "team06-chat")
    for ts in ("20261125100000000", "20261125100100000", "20261125100200000"):
        chat.put_item(Item={"session_id": "s1", "ts": ts, "text": ts})
    chat.put_item(Item={"session_id": "s2", "ts": "1", "text": "other"})
    newest = chat.query(KeyConditionExpression=Key("session_id").eq("s1"), ScanIndexForward=False, Limit=2)["Items"]
    assert [i["ts"] for i in newest] == ["20261125100200000", "20261125100100000"]


def test_table_keeps_values_after_reopen(tmp_path):
    LocalTable(LocalDatabase(tmp_path / "x.db"), "team06-jobs").put_item(Item={"job_id": "job-1", "data": "{}", "updated_at": 5})
    item = LocalTable(LocalDatabase(tmp_path / "x.db"), "team06-jobs").get_item(Key={"job_id": "job-1"})["Item"]
    assert item == {"job_id": "job-1", "data": "{}", "updated_at": 5}


def test_s3_put_get_range_and_missing(tmp_path):
    s3 = LocalS3(tmp_path / "s3")
    s3.put_object(Bucket="b", Key="uploads/a/doc.pdf", Body=b"0123456789", ContentType="application/pdf")
    assert s3.get_object(Bucket="b", Key="uploads/a/doc.pdf")["Body"].read() == b"0123456789"
    assert s3.get_object(Bucket="b", Key="uploads/a/doc.pdf", Range="bytes=0-3")["Body"].read() == b"0123"
    assert s3.content_type("uploads/a/doc.pdf") == "application/pdf"
    with pytest.raises(ClientError) as exc:
        s3.get_object(Bucket="b", Key="cache/none.json")
    assert exc.value.response["Error"]["Code"] == "NoSuchKey"
    with pytest.raises(ClientError):
        s3.get_object(Bucket="b", Key="../outside.txt")
    url = s3.generate_presigned_url("put_object", Params={"Bucket": "b", "Key": "uploads/x.pdf", "ContentType": "application/pdf"})
    assert url == "/local-s3/uploads/x.pdf"


def test_lambda_invoke_runs_worker_in_thread(monkeypatch):
    from api import worker

    seen = []
    monkeypatch.setattr(worker, "lambda_handler", lambda event, context: seen.append(event))
    res = LocalLambda().invoke(FunctionName="local-worker", InvocationType="Event", Payload=json.dumps({"job_id": "job-1", "files": []}).encode())
    assert res["StatusCode"] == 202
    import threading

    for t in threading.enumerate():
        if t.name == "worker-job-1":
            t.join(timeout=5)
    assert seen == [{"job_id": "job-1", "files": []}]


def test_http_event_and_binary_result():
    event = to_event("GET", "/api/jobs/job-1/notice", "format=md&x=%ED%95%9C", b"")
    assert event["requestContext"]["http"]["method"] == "GET"
    assert event["queryStringParameters"] == {"format": "md", "x": "한"}
    assert event["body"] is None and event["isBase64Encoded"] is False
    assert to_event("POST", "/api/x", "", b"\xff\xfe")["isBase64Encoded"] is True

    status, headers, body, media = from_result(
        {"statusCode": 200, "isBase64Encoded": True, "headers": {"Content-Type": "application/pdf", "content-disposition": "a"},
         "body": base64.b64encode(b"%PDF").decode()}
    )
    assert (status, body, media, headers) == (200, b"%PDF", "application/pdf", {"content-disposition": "a"})


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="샘플 PDF 없음")
def test_pdf_text_layer_replaces_textract():
    lines = pdf_text_lines(SAMPLE_PDF.read_bytes())
    assert len(lines) > 20
    assert all(line.page == 1 or line.page > 1 for line in lines)
    for line in lines:
        left, top, width, height = line.bbox
        assert 0 <= left <= 1 and 0 <= top <= 1 and 0 < width <= 1 and 0 < height <= 1
    res = local_ocr_document("uploads/a/doc_a.pdf", SAMPLE_PDF.read_bytes())
    assert res.file == "uploads/a/doc_a.pdf" and len(res.lines) == len(lines)


def test_image_without_tesseract_returns_no_lines(monkeypatch):
    import local.ocr as ocr

    monkeypatch.setattr(ocr, "tesseract_available", lambda: False)
    assert ocr.local_ocr_document("uploads/a/photo.jpg", b"not really a jpeg").lines == []


@pytest.mark.skipif(not SAMPLE_PDF.exists(), reason="샘플 PDF 없음")
def test_text_models_get_pdf_text_not_document_block(monkeypatch):
    from tools.extract import content_blocks

    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    blocks = content_blocks("doc_a.pdf", SAMPLE_PDF.read_bytes())
    assert len(blocks) == 1 and "text" in blocks[0] and "<document>" in blocks[0]["text"]
    monkeypatch.setenv("MODEL_PROVIDER", "bedrock")
    assert "document" in content_blocks("doc_a.pdf", SAMPLE_PDF.read_bytes())[0]


def test_openai_provider_needs_key(monkeypatch):
    from agent import make_model

    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        make_model()
