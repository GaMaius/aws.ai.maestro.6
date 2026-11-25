"""로컬 서버: API Gateway + Lambda 대신 FastAPI 한 프로세스 (docs/REBUILD.md M2).

    uv sync --group local
    uv run uvicorn server.app:app --port 8000

- /api/*        → 원래 API Lambda(api.handler.lambda_handler)를 같은 이벤트 모양으로 부른다. 경로·응답은 docs/schema.md 그대로
- /local-s3/*   → 업로드(PUT)와 서류 그림(GET). 원래는 S3 미리 서명된 주소였다 (local.aws.LocalS3)
- /             → web/dist 가 있으면 화면을 같이 준다 (cd web && npm run build). 개발 중에는 npm run dev:local 을 쓴다
처리 worker 는 같은 프로세스의 스레드에서 돈다 (local.aws.LocalLambda).
"""

from __future__ import annotations

from pathlib import Path

import local

local.install()  # api.handler 를 불러오기 전에 boto3 를 바꿔 둔다

from fastapi import FastAPI, Request, Response  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from api import handler  # noqa: E402
from local.aws import UPLOAD_PATH  # noqa: E402
from local.http import from_result, to_event  # noqa: E402

app = FastAPI(title="aws.ai.maestro.6 local", docs_url=None, redoc_url=None)
WEB_DIST = local.ROOT / "web" / "dist"


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def api(rest: str, request: Request) -> Response:
    event = to_event(request.method, f"/api/{rest}", request.url.query, await request.body())
    status, headers, content, media_type = from_result(handler.lambda_handler(event, None))
    return Response(content=content, status_code=status, headers=headers, media_type=media_type)


@app.put(UPLOAD_PATH + "{key:path}")
async def upload(key: str, request: Request) -> Response:
    if not key.startswith("uploads/"):
        return Response(status_code=403)
    handler._s3().put_object(Bucket="local", Key=key, Body=await request.body(), ContentType=request.headers.get("content-type"))
    return Response(status_code=200)


@app.get(UPLOAD_PATH + "{key:path}")
async def view(key: str) -> Response:
    s3 = handler._s3()
    try:
        path = s3.path_of(key)
    except Exception:
        return Response(status_code=403)
    if not path.is_file():
        return Response(status_code=404)
    return FileResponse(path, media_type=s3.content_type(key))


if (WEB_DIST / "index.html").is_file():
    app.mount("/", StaticFiles(directory=Path(WEB_DIST), html=True), name="web")
