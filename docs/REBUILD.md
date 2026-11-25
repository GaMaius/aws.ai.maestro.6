# 개인 포크 재구축 계획

해커톤(2026 PNU X AWS AI 마에스트로, 6팀) 동안 이 서비스는 AWS에 배포해 동작했다.
대회 계정은 계속 켜 둘 수 없으므로, 이 포크는 **포트폴리오로 보여 주는 사이트**로 구조를 바꾼다.

- 원래 AWS 서비스: 브랜치 [`archive/aws-hackathon`](https://github.com/GaMaius/aws.ai.maestro.6/tree/archive/aws-hackathon) (대회 마지막 main 그대로, 2b5dab9)
- 바꾼 main: 항상 열려 있는 데모 + 직접 돌려 보는 처리

## 구성

| 부분 | 어디서 | 비용 | 하는 일 |
| --- | --- | --- | --- |
| 데모 사이트 | GitHub Pages (`web/` 모드 `demo`) | 없음 | 서버 없이 처리 결과 예시(`docs/examples/`)를 재생한다. 업로드 → 처리 단계 → 불일치·HS·신고서·WMS 승인 → 대시보드 → AI chat 화면을 모두 눌러 볼 수 있다 |
| 직접 처리 | 내 PC (`uvicorn` 한 줄, [local/README.md](../local/README.md)) | 없음 (무료 등급) | 같은 파이썬 코드(`tools/`, `agent/`)로 실제 서류를 처리한다. AWS 대신 무료 도구를 쓴다 |
| 원래 배포 코드 | `infra/` (남겨 둠) | - | AWS에서 어떻게 배포했는지 보여 주는 기록. 대회 계정 없이는 돌리지 않는다 |

데모 화면 맨 위에는 "원래 서비스는 AWS에서 동작했고, 이 화면은 처리 결과 예시를 재생한다"는 안내가 항상 보인다.

## AWS → 무료 도구 바꾸기 (직접 처리, M2 완료)

| 원래 (AWS) | 바꿀 것 | 이유 |
| --- | --- | --- |
| Bedrock Claude (Strands `BedrockModel`) | Groq 무료 등급 (OpenAI 호환 API, Strands `OpenAIModel`). 글자 `openai/gpt-oss-120b`, 사진 `qwen/qwen3.8-27b` | 키만 있으면 무료. `MODEL_PROVIDER`로 Bedrock과 고른다. Ollama도 된다 |
| Textract | PDF 글자층(pypdfium2) + 사진은 Tesseract (kor+eng, 선택) | 생성한 서류 PDF는 글자층이 있어 OCR이 필요 없다. 사진만 OCR |
| Lambda (api + worker) | FastAPI 한 프로세스 + 백그라운드 작업 | 경로(`/api/...`)와 응답 모양(docs/schema.md)은 그대로 |
| DynamoDB 5개 테이블 | SQLite 한 파일 | 테이블 키·칸 약속(infra/README.md)을 그대로 표로 옮긴다 |
| S3 (서류 원본·캐시) | 로컬 폴더 | 미리 서명된 URL 대신 서버가 직접 받는다 |
| SES 확인 메일 | 끔 (통지 문서 내려받기로 대신) | |
| Bedrock 가드레일 | 질문 길이·주제 검사 코드 | |

코드는 이미 저장소 어댑터(`WmsAdapter`, `ShipmentStore`, `HSHistory`, 채팅 기록)로 나뉘어 있어, AWS 구현 옆에 로컬 구현을 하나씩 더한다. AWS 구현은 지우지 않는다.

## 단계

1. **M1 데모 사이트** (완료): `web/` 모드 `demo` 빌드, 내려받기 문서를 미리 만든 파일로 연결, 안내 띠, GitHub Pages 배포 워크플로
2. **M2 직접 처리** (완료): `local/` 대체물 + `server/app.py` (FastAPI) + `npm run dev:local`. 원래 코드는 고치지 않고 boto3가 대체물을 돌려주게 한다. pdfium을 여러 스레드에서 동시에 쓰던 문제(OCR 누락)도 이때 고쳤다
3. **M3 포트폴리오 정리**: README를 처음 보는 사람 기준으로 다시 쓰기 (무엇을 풀었나, AWS 구조 그림, 데모 링크, 발표 영상, 측정 숫자), 팀 규칙 문서(CLAUDE.md의 폴더 소유권 등)를 개인 저장소에 맞게 정리

## 데모 사이트 만들기

```bash
uv run python scripts/build_demo_assets.py   # 내려받기 문서 (web/public/demo/) - 예시가 바뀌었을 때만
cd web
npm ci
npm run build:demo                           # web/dist (상대 경로 빌드)
npx vite preview --mode demo                 # http://localhost:4173 에서 확인
```

main에 `web/`·`docs/examples/`가 바뀌어 올라가면 `.github/workflows/pages.yml`이 자동으로 GitHub Pages에 다시 올린다.
