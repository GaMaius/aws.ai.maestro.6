# 로컬 실행 (AWS 없이)

원래 서비스는 AWS(Bedrock · Textract · Lambda · DynamoDB · S3)에서 동작했다 (브랜치 `archive/aws-hackathon`).
여기서는 **같은 코드**를 내 PC에서 무료 도구로 돌린다. AWS 계정이 필요 없다.

| 원래 (AWS) | 로컬 | 어디 |
| --- | --- | --- |
| API Gateway + API Lambda | FastAPI 한 프로세스 | `server/app.py` |
| 처리 Lambda 비동기 호출 | 같은 프로세스의 스레드 | `local/aws.py` LocalLambda |
| DynamoDB 테이블 5개 | SQLite 파일 하나 | `local/aws.py` LocalTable |
| S3 (서류 원본·쪽 그림·캐시) | 폴더 (`.local-data/s3/`) | `local/aws.py` LocalS3 |
| Textract | PDF 글자층(pypdfium2), 사진은 Tesseract(선택) | `local/ocr.py` |
| Bedrock Claude | OpenAI 호환 API (기본 Groq 무료 등급) | `agent/__init__.py` make_model |

원래 코드(`api/`, `tools/`, `agent/`)는 그대로다. `local.install()`이 boto3가 AWS 대신 위 대체물을 돌려주게 바꿀 뿐이다.

## 1. 준비

```bash
uv sync --group local
cp local/env.example .env
```

`.env`의 `GROQ_API_KEY=`에 키를 적는다. 키는 https://console.groq.com/keys 에서 직접 만든다 (무료). `.env`는 저장소에 올라가지 않는다.

다른 OpenAI 호환 서버도 된다. 예를 들어 내 PC의 Ollama를 쓰려면 `.env`에서 `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_API_KEY=ollama`, `MODEL_ID=<받은 모델>`.

## 2. 실행

```bash
uv run --group local uvicorn server.app:app --port 8000
```

화면은 둘 중 하나로 본다.

- 개발 화면: `cd web && npm run dev:local` → http://localhost:5173 (`/api`와 `/local-s3`를 8000으로 넘긴다)
- 서버 하나로: `cd web && npm run build` 한 번 → http://localhost:8000 (서버가 `web/dist`를 같이 준다)

처음 켜면 가상 화물 기록 76건을 오늘 날짜에 맞춰 넣는다 (대시보드·AI chat용). 저장 위치는 `.local-data/` (지우면 처음 상태).

## 3. 해 볼 것

- 파일 업로드에 `samples/dev/D001/`의 PDF 네 장을 올린다 → 분류 · 읽기 · 대조 · HS · 신고서 초안 · WMS 승인
- AI chat: "이번 주 통관 지연 건 알려줘"

## 알아 둘 것

- **모델 차이**: 원래는 Claude가 PDF를 직접 읽었다. Groq 모델은 PDF를 받지 않아서 PDF 글자층을 글로 넘긴다 (`tools/extract.py` `pdf_blocks_for_text_models`). 사진 서류는 그림을 읽는 모델(`VISION_MODEL_ID`)로 보낸다. 읽기 정확도는 원래 측정값(발표 자료의 75세트 결과)과 다를 수 있다.
- **무료 등급 한도**: Groq 무료 등급은 분당 요청·토큰 한도가 있다. 서류 4장을 한 번에 올리면 한도에 걸려 일부가 실패할 수 있다. 그때는 잠시 뒤 다시 올린다.
- **OCR**: 생성한 서류 PDF는 글자층이 있어 OCR이 필요 없다. 사진·스캔 PDF는 [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)(한국어 데이터 포함)를 깔면 읽는다. 없으면 OCR 없이 진행한다 (OCR은 다시 확인의 두 번째 근거와 칸 위치 표시에만 쓴다).
- **하지 않는 것**: 확인 요청 메일(SES), Bedrock 가드레일은 로컬에서 끈다.

## 시험

```bash
uv run pytest -q tests/unit/test_local.py
```
