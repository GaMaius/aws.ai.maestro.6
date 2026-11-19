# 데이터셋 만들기 (samples/)

데이터셋은 생성기가 만든다. 거래처·품목 카탈로그와 규칙으로 세트를 만들고, 레퍼런스 기반 양식으로
서류(상업송장·포장명세서·선하증권·원산지증명서)와 정답지를 만든다. 서류는 PDF, PNG, 스캔본(글자층 없는 그림 PDF)이 섞여 있다.
값은 모두 가상이고 모든 서류에 SAMPLE이 찍힌다. 지키는 규칙, 심는 오류, 헷갈리지만 정상인 차이는 [RULES.md](RULES.md) 에 있다.

## 만드는 법 (저장소 맨 위에서)

처음 한 번: `uv venv --python 3.13 && uv pip install openpyxl reportlab pillow numpy`, 그리고 LibreOffice·poppler·tesseract 설치.

| 순서 | 하는 일 | 명령 |
|---|---|---|
| 1 | 세트 만들기 (개발용은 매번 새로, 발표용은 없을 때만) | `.venv/bin/python samples/generate_dataset.py` |
| 2 | 개발용 서류와 정답지 만들기 (약 1분) | `.venv/bin/python samples/build_samples.py` |
| 2-1 | 발표용 서류와 정답지 (처음 한 번, 약 2분) | `.venv/bin/python samples/build_samples.py --test` |
| 3 | 확인 (입력 검사, 진행 현황, 정답 값이 찍혔는지, 품명이 보이는지, 약 5분) | `.venv/bin/python samples/check_samples.py --docs` |
| 4 | 발표용 잠그기 (확인 뒤 한 번, 프롬프트를 고치기 전에) | `.venv/bin/python samples/check_samples.py --lock-test` → `samples/test_lock.json` 커밋, 태그 |

- 생성기 옵션: `--dev 75 --test 50 --error-rate 0.6 --seed 6`. 같은 시드면 같은 데이터가 나온다.
- 개발용과 발표용은 난수가 따로라서 개발용 개수나 카탈로그를 바꿔도 발표용은 그대로다. 발표용을 다시 만들려면 `--force-test` (잠그면 안 된다).
- 발표용은 `gen/items_test.csv`·`gen/parties_test.csv`(발표용 전용 품목·거래처, git에 없음)가 있어야 제대로 만들어진다. 없으면 개발용 카탈로그로만 만든다.
- 일부 세트만 서류를 다시 만들 때: `build_samples.py --only D001 D002` (정답지는 항상 전체).

## 무엇을 고치나

`data/*.csv` 는 생성기가 덮어쓰니 직접 고치지 않는다.

| 바꾸고 싶은 것 | 고칠 곳 |
|---|---|
| 거래처, 송장·주문 번호 형식 | `gen/parties.csv` |
| 품목, 정답 HS, 헷갈리는 HS(`trap_hs`), 한-중 FTA용 HS2012(`hs6_2012`), 단가, 포장, B/L 품명·비고 | `gen/items.csv` (HS는 HS 표에 있는 10자리여야 생성된다) |
| 발표용에만 쓰는 품목·거래처 | `gen/items_test.csv`, `gen/parties_test.csv` (git에 올리지 않는다) |
| 세트 비율, 날짜 범위, 인코텀즈, 결제 조건, 서류 형식 비율, 운송사, 원산지 기준 | `generate_dataset.py` 맨 위 규칙 |
| 심는 오류와 비율, 헷갈리는 차이 | `generate_dataset.py` 의 `CATEGORIES`·`KINDS`·`BL_OPTIONS`·`CO_OPTIONS`·`VARIANTS` |
| `rule_id` | `build_samples.py` 의 `RULES` |
| 상업송장·포장명세서 생김새 | `templates/templates.xlsx` |
| B/L·원산지증명서 생김새, 스캔본 효과 | `render_docs.py` |

## 만들어지는 것

| 위치 | 내용 |
|---|---|
| `data/` | 생성기 결과 (거래처, 품목, 개발용 세트). 세트의 `errors`·`variants` 칸에 심은 오류와 헷갈리는 차이(JSON) |
| `data/*_test.csv` | 발표용 세트와 발표용 전용 거래처·품목. git에 올리지 않는다 |
| `dev/<세트>/doc_a ~ doc_d` | 개발용 서류. `doc_a`·`doc_b` = 상업송장·포장명세서, `doc_c`·`doc_d` = B/L·원산지증명서 (순서는 세트마다 다름). 저장소에 올린다 |
| `test/<세트>/doc_a ~ doc_d` | 발표용 서류. git에 올리지 않는다 |
| `../eval/answers.csv` | 개발용 정답지: 심은 오류 한 줄씩 (`line`, `phase`, `variant` 칸 포함), 정상 세트는 `error_type=none` |
| `../eval/fields.csv` | 개발용: 서류마다 찍힌 핵심 칸 값 (네 서류 모두) |
| `../eval/sets.csv` | 개발용: 세트 구성(서류 자리·형식)과 품목별 정답 HS·헷갈리는 HS |
| `../eval/test/` | 발표용 정답지 세 개. git에 올리지 않는다 |
| `test_lock.json` | 발표용 잠금(해시만). 커밋한다 |

## 목표 (팀 계획)

- 약 125세트, 서류 약 500장(지금 479장). 발표용(test)은 **P0 심은 오류 20건 이상, 정상 10세트 이상**.
- 개발용 일부는 금요일 12시까지 팀에 공유한다.
- 발표용 세트는 프롬프트를 고치기 전에 `check_samples.py --lock-test` 로 잠그고(해시만 적은 `test_lock.json` 을 커밋하고 태그), 그 뒤로는 고치지 않는다.
