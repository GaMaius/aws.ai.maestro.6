# 데이터 약속
필드 이름은 예시다. 데이터셋 서류를 보고 판독 담당과 검증 담당이 함께 확정하고, 바꾸면 단톡에 알린다.
코드의 기준은 `tools/models.py`, 예시는 `docs/examples/`다. 셋이 어긋나면 CI(`tests/unit/test_examples.py`)가 실패한다.
## 약속 1. 서류 추출 결과 (read_document 반환)
- 모든 칸은 `{"raw": 문자열|null, "value": 풀어 쓴 값|null}` 형태다.
- `raw`: 모델이 서류에 적힌 그대로 옮긴 문자열. `value`·`unit`: 코드가 raw를 풀어 채운 값.
- 못 읽은 칸: `raw`와 `value`를 null로 두고 `unreadable`에 이유(흐림 · 가려짐 · 칸 없음)를 적는다.
- 모델이 스스로 매긴 확신 점수는 두지 않는다.
- `doc_type`: `bill_of_lading` | `commercial_invoice` | `packing_list` | `certificate_of_origin` | `unknown`
- 예시: `docs/examples/extract_packing_list.json`
## 약속 2. 작업 API (화면 ↔ Lambda)
| 메서드·경로 | 요청 | 응답 |
|---|---|---|
| `POST /uploads` | `{"files":[{"name","content_type"}]}` | `{"uploads":[{"key","url"}]}` (url로 S3에 직접 PUT, 몇 분 뒤 만료) |
| `POST /jobs` | `{"files":[{"key","doc_type":null}]}` | `{"job_id"}` (doc_type이 null이면 에이전트가 분류. 분류(B1)가 들어가기 전 뼈대에서는 400이므로 doc_type을 넣어 보낸다) |
| `GET /jobs/{id}` | - | 작업 상태 (`docs/examples/job_waiting_approval.json`) |
| `POST /jobs/{id}/hs` | `{"choices":[{"line","hs"}]}` | `{"declaration_draft":{...}}` |
| `POST /jobs/{id}/approve` | `{"approver"}` | `{"wms":{"status","wms_id"}}`, 불일치가 남았으면 409 |
| `POST /chat` | `{"session_id","message"}` | `docs/examples/chat_response.json` |
값 목록
- `status`: `queued` | `running` | `waiting_approval` | `done` | `failed`
- `grade`: `불일치` | `확인 필요` | `참고`
- `checked_by`: `pdf_text` | `textract` | `model_reread` | `none`
- `hs[].status`: `자동 확정` | `사람 확인 필요` | `사람 확정`, `hs[].by`: `history` | `auto_match` | `human` | null
- `wms.status`: `승인 대기` | `등록됨`, `wms.by`: `auto` | `human` | null
- `suspect`: 서류가 셋 이상일 때 다수결로 고른 서류 종류, 둘뿐이면 null
화면은 `GET /jobs/{id}`를 2초마다 부른다. 1일차 Function URL에서는 `POST /jobs` 안에서 끝까지 처리해도 되지만, 응답 형식(job_id 반환 → GET으로 조회)은 처음부터 이대로 둔다. 2일차에 비동기로 바꿔도 화면 코드는 그대로다.
## 화물 기록 (team06-shipments 한 줄)
- 예시: `docs/examples/shipment.json`
- `customs_status` 값 목록과 "통관 지연" 기준(입항 뒤 며칠)은 검증 담당이 정해 여기에 적는다.
## 약속 3. 정답지 (eval/answers.csv)
```csv
set_id,split,doc,field,planted_value,original_value,error_type,expected_rule_id,line,phase,variant
S01,dev,packing_list,total_gross_kg,6520,6250,digit_swap,X-WT-01,1,P0,
S02,dev,,,,,none,,,,
S03,dev,packing_list,invoice_no,SHE-2026 0214,SHE-2026-0214,none,,,,invoice_no_format
S04,test,certificate_of_origin,items[0].hs_code,6105.10,6109.10,trap_code,X-HS-01,1,P1,
```
- 심은 오류 하나가 한 줄(오류가 둘이면 두 줄), 정상 세트는 error_type=none 한 줄.
- split: dev(개발용) / test(발표용, 마지막에 한 번만). 발표용 정답지는 git에 올리지 않는다(eval/test/).
- doc: commercial_invoice, packing_list, bill_of_lading, certificate_of_origin.
- P0 대조 규칙은 서류 전체 값만 비교하므로 field는 서류 전체 값 이름이다: total_qty, total_gross_kg, invoice_no(약속 1의 doc_no).
  합계가 찍히지 않은 서류는 줄 값을 코드가 더한다. 약속 2의 cells가 items[0].gross_kg처럼 행 단위로 짚어도 채점은 같은 서류의 전체 값으로 묶어 센다.
- line: 값이 바뀐 품목 줄 번호(1부터). 서류 전체 값이 바뀌었으면 빈칸.
- phase: P0 = 상업송장·포장명세서의 invoice_no·total_qty·total_gross_kg, 나머지(합계, 송장 HS, B/L, 원산지증명서)는 P1.
  P0 채점은 phase=P0 줄만 정답으로 보고, P0 줄이 없는 세트는 P0 기준 정상 세트로 센다.
- variant: 정상 세트에 심은 헷갈리지만 정상인 차이(S03). 불일치로 잡으면 오탐, '참고'로 알리는 것은 괜찮다.
- 행 단위 칸(S04의 items[0].hs_code처럼)은 행 맞추기와 HS 대조를 하는 P1부터 쓴다.
- error_type은 심은 방식(samples/RULES.md의 E·V 목록), expected_rule_id는 규칙표 v1의 ID다(지금은 임시).
- 서류마다 찍힌 핵심 칸 값은 eval/fields.csv(set_id,doc,field,answer), 서류 자리·형식과 품목별 HS 정답·헷갈리는 HS는
  eval/sets.csv(set_id,split,consignee,docs,line,item,hs_answer,trap_hs), 현황 조회 질문은
  eval/queries.csv(query_id,question,expected_conditions,expected_count).
