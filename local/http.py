"""HTTP 요청 ↔ API Gateway(HTTP API, 페이로드 2.0) 이벤트 바꾸기. 웹 프레임워크에 기대지 않는다 (server/app.py가 쓴다)."""

from __future__ import annotations

import base64
from urllib.parse import parse_qsl


def to_event(method: str, path: str, query: str, body: bytes) -> dict:
    """HTTP 요청 → api.handler.lambda_handler 가 읽는 이벤트 칸. 글자가 아닌 본문은 base64 로 넣는다."""
    params = dict(parse_qsl(query, keep_blank_values=True)) if query else {}
    try:
        text, encoded = body.decode("utf-8"), False
    except UnicodeDecodeError:
        text, encoded = base64.b64encode(body).decode("ascii"), True
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": query,
        "queryStringParameters": params or None,
        "requestContext": {"http": {"method": method, "path": path}},
        "body": text or None,
        "isBase64Encoded": encoded,
    }


def from_result(result: dict) -> tuple[int, dict[str, str], bytes, str]:
    """Lambda 응답 dict → (상태 코드, 나머지 헤더, 본문 바이트, content-type). 이진 본문(isBase64Encoded, PDF)은 푼다."""
    body = result.get("body") or ""
    content = base64.b64decode(body) if result.get("isBase64Encoded") else body.encode("utf-8")
    headers = {k.lower(): v for k, v in (result.get("headers") or {}).items()}
    media_type = headers.pop("content-type", "application/json")
    return result.get("statusCode", 200), headers, content, media_type
