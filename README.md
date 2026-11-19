# aws.ai.maestro.6 — 6팀 물류 문서 자동화 Agent

2026 PNU X AWS AI 마에스트로 해커톤 6팀 저장소.
팀 계획 전체: https://claude.ai/artifact/UZ1NSdrQS2x2KyZTAwS3Sn

| 폴더 | 담당 | 내용 |
|---|---|---|
| .kiro/ | AI · AWS 통합 | Steering(team.md, agent-design.md), MCP 설정, Spec, Skill |
| agent/ | AI | 문서 처리 Agent, 현황 조회 Agent |
| tools/ | 담당별 | 도구 파일 (team.md의 파일 목록 참고) |
| eval/ | 관세 규칙 · AI | 정답지와 채점 스크립트 |
| web/ | 프론트 | 화면 |
| infra/ | AWS 통합 | IAM 정책, 배포 스크립트 |
| samples/ | AI | 데이터셋 (dev만 저장소에, test는 git 태그로 잠근 뒤) |
| refs/ | AI | 레퍼런스 출처(sources.csv). 원본 파일은 올리지 않음 |
| docs/ | 전원 | schema.md(데이터 형식 약속) |

## 처음 받았을 때
1. Kiro로 이 폴더를 열고 신뢰(Trust)를 누른다.
2. Agent Steering & Skills 패널에 team.md와 agent-design.md가 보이는지 확인한다.
3. MCP 패널에서 aws-docs, strands가 연결됐는지 확인한다. 안 보이면 설정에서 MCP를 켠다.
4. 자기 담당 폴더만 고치고, 역할별 브랜치에서 작업한다. 병합은 15·18·23·03·07시.
