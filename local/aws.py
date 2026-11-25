"""AWS 없이 돌리기 위한 대체물 (docs/REBUILD.md M2).

원래 코드(api/, tools/, agent/)는 boto3로 DynamoDB·S3·Lambda를 부른다. 로컬 실행에서는 그 코드를 고치지 않고,
boto3.client / boto3.resource 가 아래 대체물을 돌려주게 바꾼다 (install). 쓰는 API 모양만 흉내 낸다.

| 원래 | 대체물 | 저장 위치 |
| --- | --- | --- |
| DynamoDB Table (get_item·put_item·query·scan·batch_writer) | LocalTable | SQLite 파일 한 개 |
| S3 (get_object·put_object·generate_presigned_url) | LocalS3 | 폴더. 미리 서명된 주소 대신 /local-s3/<키> |
| Lambda invoke (비동기 Event) | LocalLambda | 같은 프로세스의 스레드에서 api.worker 실행 |

Textract는 local/ocr.py, Bedrock 모델은 agent.make_model(MODEL_PROVIDER=openai)이 대신한다.
"""

from __future__ import annotations

import io
import json
import re
import sqlite3
import threading
from decimal import Decimal
from pathlib import Path

from botocore.exceptions import ClientError

# 테이블 이름 → 키 칸 (infra/README.md "테이블" 약속 그대로)
KEY_SCHEMA: dict[str, tuple[str, ...]] = {
    "jobs": ("job_id",),
    "hs-history": ("importer", "item_key"),
    "wms": ("idempotency_key",),
    "shipments": ("bl_no",),
    "chat": ("session_id", "ts"),
}

UPLOAD_PATH = "/local-s3/"  # 서버(server/app.py)가 이 경로로 파일을 받고 돌려준다


def key_names(table: str) -> tuple[str, ...]:
    """테이블 이름(team06-jobs 등)의 키 칸. 접두어는 보지 않고 끝 이름으로 찾는다."""
    for suffix, keys in KEY_SCHEMA.items():
        if table.endswith(suffix):
            return keys
    raise ValueError(f"키 약속을 모르는 테이블입니다: {table}")


def _plain(value):
    """Decimal 등 JSON으로 못 쓰는 값을 바꾼다."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _client_error(code: str, operation: str, message: str = "", status: int = 400) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message or code}, "ResponseMetadata": {"HTTPStatusCode": status}}, operation)


# ---------------------------------------------------------------------------
# DynamoDB
# ---------------------------------------------------------------------------
class LocalDatabase:
    """SQLite 파일 하나에 모든 테이블을 둔다. 한 줄 = (테이블, 키, 항목 JSON)."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS items (tbl TEXT, pk TEXT, sk TEXT, item TEXT, PRIMARY KEY (tbl, pk, sk))")
        self._conn.commit()

    def execute(self, sql: str, args: tuple = ()) -> list[tuple]:
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
            self._conn.commit()
            return rows


_ATTR = re.compile(r"attribute_(not_exists|exists)\((\w+)\)")


def _condition_ok(expr: str, existing: dict | None) -> bool:
    """ConditionExpression 중 코드가 쓰는 모양만: attribute_exists / attribute_not_exists 를 OR·AND 로 이은 것."""
    parts = [p.strip() for p in re.split(r"\s+(OR|AND)\s+", expr)]
    result, op = None, None
    for part in parts:
        if part in ("OR", "AND"):
            op = part
            continue
        m = _ATTR.fullmatch(part)
        if not m:
            raise NotImplementedError(f"로컬 DynamoDB가 모르는 조건입니다: {expr}")
        has = existing is not None and m.group(2) in existing
        value = has if m.group(1) == "exists" else not has
        result = value if result is None else (result or value if op == "OR" else result and value)
    return bool(result)


class LocalTable:
    """boto3 dynamodb Table 에서 이 저장소 코드가 쓰는 부분."""

    def __init__(self, db: LocalDatabase, name: str):
        self.db, self.name = db, name
        self.keys = key_names(name)

    def _key(self, item: dict) -> tuple[str, str]:
        missing = [k for k in self.keys if k not in item]
        if missing:
            raise _client_error("ValidationException", "PutItem", f"키 칸이 없습니다: {missing}")
        return str(item[self.keys[0]]), str(item[self.keys[1]]) if len(self.keys) > 1 else ""

    def _get(self, pk: str, sk: str) -> dict | None:
        rows = self.db.execute("SELECT item FROM items WHERE tbl=? AND pk=? AND sk=?", (self.name, pk, sk))
        return json.loads(rows[0][0]) if rows else None

    def get_item(self, *, Key: dict, **_):  # noqa: N803 (boto3 인자 이름)
        item = self._get(*self._key(Key))
        return {"Item": item} if item is not None else {}

    def put_item(self, *, Item: dict, ConditionExpression: str | None = None, **_):  # noqa: N803
        item = _plain(Item)
        pk, sk = self._key(item)
        if ConditionExpression and not _condition_ok(ConditionExpression, self._get(pk, sk)):
            raise _client_error("ConditionalCheckFailedException", "PutItem", "The conditional request failed")
        self.db.execute(
            "INSERT OR REPLACE INTO items (tbl, pk, sk, item) VALUES (?, ?, ?, ?)",
            (self.name, pk, sk, json.dumps(item, ensure_ascii=False)),
        )
        return {}

    def delete_item(self, *, Key: dict, **_):  # noqa: N803
        self.db.execute("DELETE FROM items WHERE tbl=? AND pk=? AND sk=?", (self.name, *self._key(Key)))
        return {}

    def _all(self) -> list[dict]:
        return [json.loads(r[0]) for r in self.db.execute("SELECT item FROM items WHERE tbl=? ORDER BY pk, sk", (self.name,))]

    def scan(self, *, FilterExpression=None, ExpressionAttributeValues=None, **_):  # noqa: N803
        items = self._all()
        if isinstance(FilterExpression, str):
            m = re.fullmatch(r"begins_with\((\w+),\s*(:\w+)\)", FilterExpression.strip())
            if not m:
                raise NotImplementedError(f"로컬 DynamoDB가 모르는 FilterExpression입니다: {FilterExpression}")
            prefix = (ExpressionAttributeValues or {})[m.group(2)]
            items = [i for i in items if str(i.get(m.group(1), "")).startswith(prefix)]
        elif FilterExpression is not None:
            raise NotImplementedError("로컬 DynamoDB는 문자열 FilterExpression만 받습니다")
        return {"Items": items, "Count": len(items)}

    def query(self, *, KeyConditionExpression, ScanIndexForward: bool = True, Limit: int | None = None, **_):  # noqa: N803
        expr = KeyConditionExpression.get_expression()
        if expr["operator"] != "=":
            raise NotImplementedError("로컬 DynamoDB query는 파티션 키 = 값만 받습니다")
        name, value = expr["values"][0].name, expr["values"][1]
        if name != self.keys[0]:
            raise NotImplementedError(f"파티션 키가 아닌 칸으로 query 했습니다: {name}")
        rows = self.db.execute(
            f"SELECT item FROM items WHERE tbl=? AND pk=? ORDER BY sk {'ASC' if ScanIndexForward else 'DESC'}",
            (self.name, str(value)),
        )
        items = [json.loads(r[0]) for r in rows][: Limit or None]
        return {"Items": items, "Count": len(items)}

    def batch_writer(self, **_):
        table = self

        class _Batch:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def put_item(self, *, Item: dict):  # noqa: N803
                table.put_item(Item=Item)

        return _Batch()


class LocalDynamoResource:
    def __init__(self, db: LocalDatabase):
        self.db = db

    def Table(self, name: str) -> LocalTable:  # noqa: N802 (boto3 이름)
        return LocalTable(self.db, name)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------
class _Body(io.BytesIO):
    pass


class LocalS3:
    """boto3 s3 클라이언트에서 쓰는 부분. 버킷 이름은 무시하고 폴더 하나에 키 경로대로 둔다."""

    def __init__(self, root: Path):
        self.root = root

    def path_of(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise _client_error("AccessDenied", "GetObject", "키가 저장 폴더 밖을 가리킵니다", 403)
        return path

    def put_object(self, *, Key: str, Body, ContentType: str | None = None, **_):  # noqa: N803
        path = self.path_of(Key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Body if isinstance(Body, bytes) else Body.encode("utf-8") if isinstance(Body, str) else Body.read())
        if ContentType:
            path.with_name(path.name + ".type").write_text(ContentType, encoding="utf-8")
        return {}

    def get_object(self, *, Key: str, Range: str | None = None, **_):  # noqa: N803
        path = self.path_of(Key)
        if not path.is_file():
            raise _client_error("NoSuchKey", "GetObject", "The specified key does not exist.", 404)
        data = path.read_bytes()
        if Range:
            m = re.fullmatch(r"bytes=(\d+)-(\d*)", Range)
            if m:
                data = data[int(m.group(1)) : int(m.group(2)) + 1 if m.group(2) else None]
        return {"Body": _Body(data), "ContentLength": len(data), "ContentType": self.content_type(Key)}

    def head_object(self, *, Key: str, **_):  # noqa: N803
        path = self.path_of(Key)
        if not path.is_file():
            raise _client_error("404", "HeadObject", "Not Found", 404)
        return {"ContentLength": path.stat().st_size, "ContentType": self.content_type(Key)}

    def content_type(self, key: str) -> str:
        meta = self.path_of(key).with_name(self.path_of(key).name + ".type")
        return meta.read_text(encoding="utf-8") if meta.is_file() else "application/octet-stream"

    def generate_presigned_url(self, ClientMethod: str, Params: dict, ExpiresIn: int = 0, HttpMethod: str | None = None):  # noqa: N803
        """서명 대신 서버 경로를 준다. 같은 주소(서버)라 브라우저가 그대로 PUT·GET 한다."""
        return UPLOAD_PATH + Params["Key"]


# ---------------------------------------------------------------------------
# Lambda (처리 worker 비동기 호출)
# ---------------------------------------------------------------------------
class LocalLambda:
    def invoke(self, *, FunctionName: str, InvocationType: str = "Event", Payload: bytes = b"{}", **_):  # noqa: N803
        event = json.loads(Payload)

        def run() -> None:
            from api import worker

            try:
                worker.lambda_handler(event, None)
            except Exception as exc:  # 스레드 안 예외는 로그로 남긴다 (worker가 작업 상태를 failed로 저장한다)
                print(f"[local] worker 실패 job={event.get('job_id')} {type(exc).__name__}: {exc}")

        threading.Thread(target=run, name=f"worker-{event.get('job_id')}", daemon=True).start()
        return {"StatusCode": 202}
