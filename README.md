# aws.ai.maestro.6: 6팀 물류 문서 자동화 Agent

> **포트폴리오 데모**: https://gamaius.github.io/aws.ai.maestro.6/ (서버 없이 처리 결과 예시를 재생하는 화면)
> 원래 서비스는 해커톤 동안 AWS(Bedrock·Textract·Lambda·DynamoDB)에 배포해 동작했다. 그 코드는 브랜치 [`archive/aws-hackathon`](https://github.com/GaMaius/aws.ai.maestro.6/tree/archive/aws-hackathon)에 그대로 있다.
> 이 포크를 어떻게 바꾸는지는 [docs/REBUILD.md](docs/REBUILD.md)에 있다.

부산항 포워더 실무자가 화물 한 건의 서류 묶음(B/L, 상업송장, 포장명세서, 원산지증명서)을 올리면,
에이전트가 서류를 분류해 핵심 항목을 읽고, 서류끼리 대조해 오류를 근거와 함께 짚고,
HS 코드를 확정하거나 추천해 신고서 초안을 채우고, 문제가 없으면 가상 WMS에 바로 등록한다.
"이번 주 통관 지연 건 알려줘"처럼 물어 현황을 본다.
- 2026 PNU X AWS AI 마에스트로 해커톤 6팀
- 스택: Amazon Bedrock(Claude, global 추론 프로필), Amazon Textract, Strands Agents SDK, AWS Lambda, S3, DynamoDB (모두 ap-northeast-2)
- 원칙: AI는 읽기, 판정은 코드 (`.kiro/steering/agent-design.md`)

## 문서
- 팀 구성과 누가 무엇을 하나: [TEAM.md](TEAM.md)
- 협업 규칙과 폴더 담당: [CONTRIBUTING.md](CONTRIBUTING.md)
- 데이터 약속: [docs/schema.md](docs/schema.md)
- 작업 지도: [.kiro/specs/00-skeleton/e2e-plan.md](.kiro/specs/00-skeleton/e2e-plan.md)

## 처음 받았을 때
1. `uv sync && uv run pytest`
2. Kiro로 이 폴더를 열고 신뢰(Trust)를 누른다.
3. Agent Steering & Skills 패널에 team.md와 agent-design.md가 보이는지 확인한다.
4. MCP 패널에서 aws-docs, strands가 연결됐는지 확인한다. 안 보이면 설정에서 MCP를 켠다.
5. TEAM.md에서 내 번호를 확인하고, GitHub 이슈에서 라벨 `담당:<내 담당>`으로 내 작업을 본다.

## 공개 저장소 주의
- `samples/`는 dev 세트만 올린다. test 세트는 올리지 않고 해시 파일 `samples/test_lock.json`으로 잠근다.
- `refs/`는 출처(`refs/sources.csv`)만 올린다. 레퍼런스 원본은 저작권 때문에 올리지 않는다.
- 키·토큰·계정 번호를 어떤 파일에도 적지 않는다.
