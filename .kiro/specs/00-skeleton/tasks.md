# 00-skeleton 작업

- [ ] S1 모델 호출: 인사·structured_output·도구 호출 확인하고 design.md에 기록(완료). 서류 읽기 시간은 서류 받은 뒤.
- [ ] S2 상업송장·포장명세서 읽기: `tools/extract.py read_document` + 가짜 모델 단위 테스트(완료). 실제 서류 확인은 서류 받은 뒤.
- [x] S3 대조 규칙 하나: `tools/validate.py cross_check` (X-WT-01) + 일치·불일치·못 읽음 단위 테스트
- [ ] S4 빈 Lambda 배포: `infra/` 정책·스크립트 작성(완료). `iam:CreateRole` 권한이 없어 실행이 막힘. 권한 받은 뒤 create.sh와 curl 확인.
- [ ] S5 끝까지 한 번: `api/handler.py`, `agent/document_agent.py` 작성(완료). 실제 실행은 S4 뒤.
- [x] S6 인계 준비: `infra/README.md`

- [x] 협업 뼈대 (사용자 요청): 역할 사이 모델, 도구 함수 모양(NotImplementedError), 의존성 Protocol, 메모리 구현, 501 경로, 폴더별 README, 분배표(e2e-plan.md 5번)

## 나중 (이번 범위 밖)
- classify_document (doc_type null 처리)
- POST /uploads (미리 서명된 URL)
- 판독 캐시 (파일 해시 + 모델 ID + 지시문 버전), no_cache 옵션
- 도구를 고르는 문서 처리 Agent 루프, finish_report 조건 검사
- B/L · 원산지증명서, 총수량 · 송장 번호 규칙
- POST /jobs 비동기화
- .kiro/skills 네 개 (내일 팀 세팅)
