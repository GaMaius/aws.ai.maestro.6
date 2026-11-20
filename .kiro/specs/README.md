# Spec 폴더 규칙
- 폴더 하나 = 기능 하나. 폴더마다 주 담당 한 명이 파일을 고친다. 협업 담당은 PR 리뷰와 댓글로 참여하고, 남의 폴더는 직접 고치지 않는다.
- 00-skeleton: 오늘 밤 뼈대 (주 담당 PM)
- 01-documents: Spec 1 서류 처리, 기능 ①② (주 담당 1번 판독, 협업 2번 검증) — 금요일 10~12시 팀이 함께 승인
- 02-hs-declaration: Spec 2 HS와 신고서, 기능 ③ (주 담당 2번 검증) — 금요일 오후
- 03-wms-query: Spec 3 연동과 조회, 기능 ④⑤ (주 담당 4번 서버, 협업 1번 판독) — 금요일 오후
- 3번 화면과 5번 발표는 Spec 폴더 대신 `web/README.md`, `docs/presentation/README.md`와 GitHub 이슈로 진행한다. 필요하면 04-web, 05-presentation을 만든다.
- Spec 프롬프트를 보낼 때 입력창에서 #agent-design.md 와 #schema.md 를 붙인다.
- tasks.md는 작업 하나씩 실행하고, 작업마다 diff 확인 → 테스트 → 커밋.
