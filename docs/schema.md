# 데이터 형식 약속 (초안, 금요일 10~12시에 팀이 확정)

필드는 예시다. 데이터셋 서류를 보고 AI 담당과 관세 규칙 담당이 같이 확정한다. 바꾸기 전에 팀에 먼저 알린다.

## 약속 1. 서류 추출 결과 (read_document가 돌려주는 것)

```json
{
  "doc_type": "packing_list",
  "file": "uploads/sample-001/packing_list.pdf",
  "doc_no": {"raw": "PL-2026-001", "value": "PL-2026-001"},
  "items": [
    {
      "line": 1,
      "item_code": {"raw": "BP-200", "value": "BP-200"},
      "name": {"raw": "LITHIUM-ION BATTERY PACK", "value": "lithium-ion battery pack"},
      "hs_code": {"raw": "8507.60", "value": "850760"},
      "qty": {"raw": "500 CTNS", "value": 500, "unit": "CTN"},
      "gross_kg": {"raw": "6,520.00 KGS", "value": 6520.0},
      "net_kg": {"raw": null, "value": null, "unreadable": "흐림"}
    }
  ]
}
```

## 약속 2. API와 작업 상태

```text
POST /uploads       요청  {"files": [{"name": "bl.jpg", "content_type": "image/jpeg"},
                                     {"name": "invoice.pdf", "content_type": "application/pdf"}]}
                    응답  {"uploads": [{"key": "uploads/sample-001/bl.jpg", "url": "(미리 서명된 S3 주소)"}, ...]}
                    (화면은 받은 url로 파일을 S3에 바로 PUT. 주소는 몇 분 뒤 만료)

POST /jobs          요청  {"files": [{"key": "uploads/sample-001/bl.jpg", "doc_type": null},
                                     {"key": "uploads/sample-001/invoice.pdf", "doc_type": null}]}
                    응답  {"job_id": "job-7c1e"}
                    (doc_type은 비워 두면 에이전트가 분류. 사용자가 화면에서 고친 값이 있으면 그 값)

GET /jobs/job-7c1e  응답
{
  "status": "running",              ← queued | running | waiting_approval | done | failed
                                       (waiting_approval: 예외가 있어 사람 확인을 기다림. 예외가 없으면 바로 done)
  "steps": [
    {"tool": "classify_document", "summary": "bl.jpg → 선하증권", "ok": true},
    {"tool": "read_document", "summary": "invoice.pdf → 상업송장, 1행", "ok": true},
    {"tool": "cross_check", "summary": "불일치 1건", "ok": true},
    {"tool": "reread_field", "summary": "포장명세서 1행 총중량: Textract에서 6,520 확인", "ok": true}
  ],
  "result": {
    "issues": [{
      "rule_id": "X-WT-01",
      "grade": "불일치",             ← 불일치 | 확인 필요 | 참고
      "cells": [
        {"doc": "commercial_invoice", "field": "items[0].gross_kg", "raw": "6,250.00 KGS"},
        {"doc": "packing_list", "field": "items[0].gross_kg", "raw": "6,520.00 KGS"}
      ],
      "suspect": "packing_list",     ← 서류가 셋 이상일 때 다수결로 고른 쪽. 둘뿐이면 null
      "evidence": "상업송장 1행 총중량 6,250kg과 포장명세서 6,520kg이 다릅니다.",
      "checked_by": "textract"       ← pdf_text | textract | model_reread | none
    }],
    "hs": [{"line": 1, "status": "사람 확인 필요", "by": null, "hs_code": null,
            ← status: 자동 확정 | 사람 확인 필요 | 사람 확정, by: history | auto_match | human
            "candidates": [
      {"hs": "8507.60-XXXX", "name": "(HS 표의 품목명)", "reason": "품명과 용도 칸 근거"}]}],
    "declaration_draft": {
      "fields": [{"name": "품명", "value": "LITHIUM-ION BATTERY PACK",
                  "source": "commercial_invoice.items[0].name"}],
      "blank_fields": ["items[0].gross_kg"],   ← 불일치·확인 필요·HS 미확정이라 비워 둔 칸
      "pdf_url": null                          ← PDF는 여유가 있을 때
    },
    "wms": {"status": "승인 대기", "by": null}       ← 승인 대기 | 등록됨, by: auto(예외 없으면 바로) | human
  }
}

POST /jobs/job-7c1e/hs       요청  {"choices": [{"line": 1, "hs": "8507.60-XXXX"}]}
                             응답  {"declaration_draft": {...}}      ← 초안을 다시 채우고 확정 이력에 저장. 남은 예외가 없으면 바로 WMS 등록
POST /jobs/job-7c1e/approve  요청  {"approver": "김동현"}
                             응답  {"wms": {"status": "등록됨", "wms_id": "WMS-0001"}}
                             (확인 필요가 남은 건만 씀. 불일치가 남아 있으면 409와 남은 issues. 같은 건을 다시 보내도 한 번만 등록)

POST /chat          요청  {"session_id": "s-01", "message": "이번 주 통관 지연 건 알려줘"}
                    응답  {"answer": "...", "filters": {"status": "통관 지연", "period": "this_week"},
                           "period_resolved": {"from": "2026-11-16", "to": "2026-11-22"}, "rows": [...]}

화물 기록 (team06-shipments 한 줄. finish_report가 넣고, WMS에 등록되면 상태를 고침)
{"bl_no": "BL-2026-0001", "consignee": "샘플무역", "item": "리튬이온 배터리팩",
 "arrived_at": "2026-11-17", "customs_status": "심사 중", "last_event_at": "2026-11-18", "job_id": "job-7c1e"}
```

## 약속 3. 정답지 (eval/answers.csv)

```csv
set_id,split,doc,field,planted_value,original_value,error_type,expected_rule_id
S01,dev,packing_list,total_gross_kg,6520,6250,digit_swap,X-WT-01
S02,dev,,,,,none,
S03,test,commercial_invoice,items[0].hs_code,850790,850760,wrong_code,X-HS-01
```

- 심은 오류 하나가 한 줄, 정상 세트는 error_type=none 한 줄.
- split: dev(개발용) / test(발표용, 마지막에 한 번만). 발표용 정답지는 git 에 올리지 않는다(eval/test/).
- P0 대조 규칙은 서류 전체 값만 비교하므로 field 는 서류 전체 값 이름이다: total_qty, total_gross_kg, invoice_no(약속 1 의 doc_no). 합계가 찍히지 않은 서류는 줄 값을 코드가 더한다. 약속 2 의 cells 가 items[0].gross_kg 처럼 행 단위로 짚어도 채점은 같은 서류의 전체 값으로 묶어 센다. (회의에서 확정)
- 행 단위 칸(S03 의 items[0].hs_code 처럼)은 행 맞추기와 HS 대조를 하는 P1 부터 쓴다. 그때 바뀐 행 번호도 정답지에 적는다.
- error_type 은 심은 방식(samples/RULES.md 의 E 목록), expected_rule_id 는 규칙표 v1 의 ID 다(지금은 임시).
- 핵심 칸 정답 값은 eval/fields.csv, 서류 종류와 품목별 HS 정답은 eval/sets.csv, 현황 조회 질문은 eval/queries.csv.
