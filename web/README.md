# web/ 화면 (담당: 화면)

## 먼저 정할 것 (G1)
- [ ] 기술: (예: React + Vite, 순수 HTML/JS)
- [ ] 호스팅 위치: 서버 담당과 정함 (F5)
- [ ] API 주소를 바꾸는 방법: 환경 변수 하나 (예: `API_BASE`). 처음에는 가짜 응답 모드로 둔다

정하면 이 칸을 채우고, 실행 방법을 아래에 적는다.

## 화면과 쓰는 API (docs/schema.md 약속 2)
| 작업 | 화면 | 부르는 것 | 가짜 응답 |
|---|---|---|---|
| G2 | 업로드 (서류 종류 고치기 포함) | `POST /uploads` → url로 S3에 PUT → `POST /jobs` | 없음 (job_id만 흉내) |
| G3 | 진행 | `GET /jobs/{id}` 2초마다, `steps` | `docs/examples/job_waiting_approval.json` |
| G4 | 결과: 오류 목록 | `result.issues` (등급, 근거, 서류·칸·raw, checked_by) | 같은 파일 |
| G5 | 결과: HS 선택 | `result.hs`, `POST /jobs/{id}/hs` | 같은 파일 |
| G6 | 결과: 신고서 초안 | `result.declaration_draft`, "사람 검토 전 초안" 표시 | 같은 파일 |
| G7 | 결과: WMS 상태·승인 | `result.wms`, `POST /jobs/{id}/approve` (409면 안내) | 같은 파일 |
| G8 | 현황 채팅 | `POST /chat` | `docs/examples/chat_response.json` |

## 규칙
- 서버가 아직 없는 경로는 501을 돌려준다. 그동안은 가짜 응답으로 화면을 만든다.
- 응답 칸 이름은 docs/examples/와 똑같이 쓴다. 바뀌면 공용 파일 변경으로 단톡에 알림이 온다.
- 서류 원본이나 키를 화면 코드에 넣지 않는다.
