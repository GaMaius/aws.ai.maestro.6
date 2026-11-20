"""scripts/github_setup.py 계획 부분 테스트 (GitHub 호출 없음). tasks.csv가 깨지면 CI가 잡는다."""

from scripts.github_setup import PHASES, ROLES, issue_body, issue_title, labels_for, load_tasks, plan_labels


def test_tasks_csv_is_valid():
    tasks = load_tasks()
    assert len(tasks) >= 40
    assert {t["role"] for t in tasks} == set(ROLES)


def test_every_role_has_p0_or_first_work():
    tasks = load_tasks()
    for role in ROLES:
        assert any(t["role"] == role for t in tasks), role


def test_issue_text():
    task = next(t for t in load_tasks() if t["id"] == "B7")
    assert issue_title(task) == "[B7] cross_check 확장"
    body = issue_body(task)
    assert "[B5] [B6]" in body and "`tools/validate.py`" in body and "feat/b7-" in body
    assert labels_for(task) == ["담당:검증", "단계:P0"]
    assert "**담당**: 2번 검증 담당" in body


def test_shared_file_label():
    task = next(t for t in load_tasks() if t["id"] == "B2")
    assert "공용 파일" in labels_for(task)


def test_labels_cover_roles_and_phases():
    names = {name for name, _, _ in plan_labels()}
    assert {f"담당:{r}" for r in ROLES} <= names
    assert {f"단계:{p}" for p in PHASES} <= names
