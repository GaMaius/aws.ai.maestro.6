"""finish_report. 담당: 판독. 규칙: .kiro/steering/agent-design.md 1·5번, 형식: docs/schema.md

작업: e2e-plan.md B9 (P0~P1).
"""

from tools.models import JobState, ReportCheck


def finish_report(state: JobState) -> ReportCheck:
    """리포트를 마무리해도 되는지 코드로 검사한다.

    언제: 에이전트가 일을 다 했다고 판단할 때. 못 채우면 missing을 보고 빠진 도구를 다시 부른다.
    받는 것: JobState.
    반환: ReportCheck. 검사 조건 (agent-design.md 1번):
      - 올라온 서류를 모두 분류하고 읽었다
      - 마지막 읽기 뒤에 cross_check를 돌렸다 (check_seq == read_seq)
      - 불일치 칸을 모두 다시 확인했다
      - 모든 품목에 recommend_hs를 돌렸다
    ok이면 부른 쪽이 작업을 저장하고, 화물 기록을 쓰고, 자동 등록 조건을 검사한다.
    """
    print(f"[tool] finish_report job={state.job_id}")
    raise NotImplementedError("B9: 리포트 조건 검사 (판독 담당)")
