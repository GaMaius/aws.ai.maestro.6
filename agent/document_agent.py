"""문서 처리 Agent (뼈대). 담당: 판독. 규칙: .kiro/steering/agent-design.md 1·2번

뼈대(S5)는 순서를 코드가 정한다: 서류마다 read_document(동시에) → cross_check.
도구를 고르는 에이전트 루프와 finish_report 조건 검사는 Spec 1에서 만든다.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from tools.extract import ModelReader, ReadError, read_document
from tools.models import DOC_TYPE_KO, DocType, ExtractedDocument, Issue, IssueCell, Job, JobResult, Step
from tools.validate import cross_check

MAX_FILES = 10
MAX_BYTES = 4_500_000  # Bedrock 문서 블록 한도 (4.5MB)
MAX_WORKERS = 4

# S3 키 → 파일 바이트
Fetch = Callable[[str], bytes]


def _read_one(key: str, doc_type: DocType, fetch: Fetch, reader: ModelReader | None):
    """서류 한 장을 읽는다. 실패하면 (None, 이유)."""
    try:
        data = fetch(key)
        if len(data) > MAX_BYTES:
            raise ReadError(f"파일이 너무 큽니다 ({len(data):,}바이트, 최대 {MAX_BYTES:,})")
        return read_document(key, data, doc_type, reader=reader), None
    except ReadError as exc:
        return None, str(exc)
    except Exception as exc:  # S3 오류 등
        return None, f"{type(exc).__name__}: {exc}"


def run_job(
    job_id: str, files: list[dict], fetch: Fetch, *, reader: ModelReader | None = None
) -> Job:
    """서류 묶음 하나를 처리해 Job(약속 2)을 돌려준다.

    언제: POST /jobs 안에서 (뼈대는 동기 처리).
    받는 것: job_id, files([{"key", "doc_type"}], doc_type 필수), fetch(S3 키 → 바이트), reader(테스트용 가짜 모델).
    반환: Job. 읽기 실패는 READ-FAIL '확인 필요'로 남기고 그 서류는 대조에서 뺀다.
    """
    steps: list[Step] = []
    issues: list[Issue] = []
    docs: list[ExtractedDocument] = []

    # 서류는 따로, 동시에 읽는다 (다른 서류 값을 프롬프트에 넣지 않는다)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_read_one, f["key"], f["doc_type"], fetch, reader) for f in files]
        results = [fut.result() for fut in futures]

    for f, (doc, error) in zip(files, results):
        name = f["key"].rsplit("/", 1)[-1]
        ko = DOC_TYPE_KO[f["doc_type"]]
        if doc is None:
            steps.append(Step(tool="read_document", summary=f"{name} → {ko} 읽기 실패: {error}", ok=False))
            issues.append(
                Issue(
                    rule_id="READ-FAIL",
                    grade="확인 필요",
                    cells=[IssueCell(doc=f["doc_type"], field="*", raw=None)],
                    evidence=f"{ko}({name})를 읽지 못했습니다. 다시 올리거나 직접 확인해 주세요.",
                )
            )
            continue
        docs.append(doc)
        steps.append(Step(tool="read_document", summary=f"{name} → {ko}, {len(doc.items)}행", ok=True))

    found = cross_check(docs)
    issues.extend(found)
    counts = {g: sum(1 for i in found if i.grade == g) for g in ("불일치", "확인 필요", "참고")}
    summary = ", ".join(f"{g} {n}건" for g, n in counts.items() if n) or "문제 없음"
    steps.append(Step(tool="cross_check", summary=summary, ok=True))

    pending = any(i.grade in ("불일치", "확인 필요") for i in issues)
    return Job(
        job_id=job_id,
        status="waiting_approval" if pending else "done",
        steps=steps,
        result=JobResult(issues=issues),
    )
