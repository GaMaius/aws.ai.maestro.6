"""끝까지 측정 (FB15 #172). 담당: 판독(실행·판독 결과 남기기). 형식별 채점 표는 검증(eval/score.py, 2번).

개발용 세트를 실제 판독으로 run_job 끝까지 돌린다. 처리 Lambda(api/worker.py)와 같은 조건이다:
doc_type을 비워 분류부터, 세트의 서류를 모두(상업송장·포장명세서·선하증권·원산지증명서) 올리고,
HS는 recommend_hs(모델 없음, 빈 확정 이력 = 평가 전 초기화 상태)를 붙인다.
발표용(samples/test, eval/test)은 열지 않는다.

- 세트마다 결과를 한 줄씩 바로 eval/results/e2e_dev.jsonl에 쓴다 (중간에 멈춰도 그때까지 남고, 다시 돌리면 이어서 한다).
  형식, 상태, 시간, 모델 호출 수, 분류, 읽은 서류(docs), 문제(issues), HS, 단계. 2번이 이 파일로 모델 호출 없이 다시 채점한다.
- 판독(read_document)은 로컬 판독 캐시(.cache/read/, git 제외)에 남긴다. 규칙을 바꿔 다시 돌릴 때 읽기 호출을 아낀다.
- --report: 파일만 읽어 형식(PDF·PNG·스캔)별 분류·읽기·탐지·오탐·HS·시간을 낸다 (모델 호출 없음).

세트 고르기 (--per-format N, 기본 10 → 30세트): 상업송장 형식(pdf·png·scan)마다 세트 번호 순으로
심은 P0 오류 4 · 정상 2 · 헷갈리지만 정상(변형) 2 · P1 오류 2를 고르고, 모자라면 같은 형식의 남은 세트로 채운다.
모델 호출은 세트당 약 10번 (분류 4 + 읽기 4 + 스캔·사진의 다시 확인, #162 측정).

실행:
    export MODEL_ID=<global 추론 프로필 ID>
    uv run python -m samples.measure_e2e                 # 30세트, 이미 잰 세트는 건너뜀
    uv run python -m samples.measure_e2e --report        # 모델 호출 없이 표만
    uv run python -m samples.measure_e2e --sets D003 D005 --out /tmp/x.jsonl
"""

import argparse
import contextlib
import csv
import io
import json
import statistics
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / "samples" / "dev"
EVAL = ROOT / "eval"
OUT = EVAL / "results" / "e2e_dev.jsonl"
SUMMARY = EVAL / "results" / "e2e_dev_summary.json"
CACHE = ROOT / ".cache" / "read"
FORMATS = ("pdf", "png", "scan")
QUOTA = (("P0", 4), ("정상", 2), ("변형", 2), ("P1", 2))  # 형식마다. 합이 기본 per_format(10)


# ---------------------------------------------------------------------------
# 세트 고르기
# ---------------------------------------------------------------------------
def dev_sets() -> dict[str, dict[str, str]]:
    """개발용 세트 → {서류 종류: 형식}. 세트의 첫 줄(eval/sets.csv)에서 읽는다."""
    sets: dict[str, dict[str, str]] = {}
    with (EVAL / "sets.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] != "dev" or r["set_id"] in sets:
                continue
            kv = dict(part.split("=", 1) for part in r["docs"].split(";"))
            sets[r["set_id"]] = {kv[f"doc_{s}"]: kv[f"fmt_{s}"] for s in "abcd" if f"doc_{s}" in kv}
    return sets


def set_kind() -> dict[str, str]:
    """세트 → 갈래. P0 오류가 있으면 P0, 그다음 P1, 변형(헷갈리지만 정상), 정상 (eval/answers.csv)."""
    kinds: dict[str, set[str]] = defaultdict(set)
    with (EVAL / "answers.csv").open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if r["split"] != "dev":
                continue
            if r["error_type"] != "none":
                kinds[r["set_id"]].add(r["phase"] or "P1")
            else:
                kinds[r["set_id"]].add("변형" if r.get("variant") else "정상")
    order = ("P0", "P1", "변형", "정상")
    return {sid: next(k for k in order if k in ks) for sid, ks in kinds.items()}


def pick_sets(per_format: int = 10) -> list[str]:
    """상업송장 형식마다 per_format세트. 갈래 몫(QUOTA)을 세트 번호 순으로 채우고 모자라면 남은 세트로 채운다."""
    sets, kinds = dev_sets(), set_kind()
    picked: list[str] = []
    for fmt in FORMATS:
        pool = sorted(s for s, f in sets.items() if f.get("commercial_invoice") == fmt)
        chosen: list[str] = []
        scale = per_format / sum(n for _, n in QUOTA)
        for kind, n in QUOTA:
            chosen += [s for s in pool if kinds.get(s) == kind and s not in chosen][: round(n * scale)]
        chosen += [s for s in pool if s not in chosen][: per_format - len(chosen)]
        picked += sorted(chosen[:per_format])
    return picked


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
class LocalReadCache:
    """판독 캐시(tools.extract.ReadCache)의 로컬 파일판. <키>.json 한 파일에 한 판독."""

    def __init__(self, root: Path):
        self.root = root

    def get(self, key: str) -> str | None:
        path = self.root / f"{key}.json"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def put(self, key: str, value: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{key}.json").write_text(value, encoding="utf-8")


class _EmptyHistory:
    """빈 확정 이력 (평가는 이력을 비운 상태에서 시작한다, agent-design.md 11번)."""

    def get(self, importer: str, item_key: str) -> str | None:
        return None

    def put(self, importer: str, item_key: str, hs: str, job_id: str) -> None:
        return None


def _count_model_calls() -> dict:
    """Bedrock 모델 호출(BedrockModel.stream)을 센다. 도구 안의 분류·읽기·다시 확인과 루프 차례가 모두 여기를 지난다."""
    from strands.models import bedrock

    calls = {"model": 0}
    lock = threading.Lock()
    original = bedrock.BedrockModel.stream

    async def counting(self, *args, **kwargs):
        with lock:
            calls["model"] += 1
        async for event in original(self, *args, **kwargs):
            yield event

    bedrock.BedrockModel.stream = counting
    return calls


def files_of(set_id: str) -> list[tuple[str, str]]:
    """세트 → [(파일 키, 정답 종류)]. 키는 저장소 기준 경로."""
    with (EVAL / "sets.csv").open(encoding="utf-8", newline="") as fh:
        row = next(r for r in csv.DictReader(fh) if r["set_id"] == set_id and r["split"] == "dev")
    kv = dict(part.split("=", 1) for part in row["docs"].split(";"))
    out = []
    for slot in "abcd":
        if f"doc_{slot}" in kv:
            [path] = sorted((DEV / set_id).glob(f"doc_{slot}.*"))
            out.append((str(path.relative_to(ROOT)), kv[f"doc_{slot}"]))
    return out


def run_set(set_id: str, calls: dict) -> dict:
    """세트 하나를 run_job으로 끝까지. 결과 한 줄(dict)."""
    from agent.document_agent import run_job
    from tools import hs
    from tools.models import DOC_TYPE_KO

    table = hs.load_hs_table()
    files = files_of(set_id)
    read: list = []
    before, started = calls["model"], time.perf_counter()
    try:
        job = run_job(
            f"job-e2e-{set_id.lower()}", [{"key": k, "doc_type": None} for k, _ in files], lambda key: (ROOT / key).read_bytes(),
            hs_recommender=lambda docs, line: hs.recommend_hs(docs, line, "", history=_EmptyHistory(), table=table),
            on_docs=read.extend,
        )
        error = job.error
    except Exception as exc:  # 측정은 멈추지 않고 기록한다
        job, error = None, f"{type(exc).__name__}: {exc}"
    seconds = round(time.perf_counter() - started, 1)
    steps = job.steps if job else []
    got = {s.summary.split(" → ")[0]: s.summary for s in steps if s.tool == "classify_document" and s.ok}
    classified = []
    for key, expected in files:
        name = key.rsplit("/", 1)[-1]
        classified.append([name, expected, name in got and f"→ {DOC_TYPE_KO[expected]} (" in got[name]])
    result = job.result if job and job.result else None
    return {
        "set_id": set_id, "formats": dev_sets()[set_id], "status": job.status if job else None, "error": error,
        "seconds": seconds, "model_calls": calls["model"] - before, "classified": classified,
        "docs": [d.model_dump(mode="json") for d in read],
        "issues": [i.model_dump(mode="json") for i in result.issues] if result else [],
        "hs": [h.model_dump(mode="json") for h in result.hs] if result else [],
        "steps": [s.model_dump(mode="json") for s in steps],
    }


def done_sets(out: Path) -> set[str]:
    if not out.exists():
        return set()
    return {json.loads(line)["set_id"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}


def measure(set_ids: list[str], out: Path, cache: Path | None) -> None:
    from tools import extract

    if cache is not None:
        local = LocalReadCache(cache)
        extract._default_cache = lambda: local  # 처리 Lambda의 S3 판독 캐시 대신 로컬 (모델 ID·지시문 버전이 키에 들어간다)
    calls = _count_model_calls()
    skip = done_sets(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    todo = [s for s in set_ids if s not in skip]
    print(f"[e2e] {len(set_ids)}세트 중 {len(todo)}세트를 잰다 (이미 잰 {len(set_ids) - len(todo)}세트는 건너뜀) → {out}")
    for n, set_id in enumerate(todo, 1):
        with contextlib.redirect_stdout(io.StringIO()):  # 도구의 [tool] 출력은 숨긴다
            row = run_set(set_id, calls)
        with out.open("a", encoding="utf-8") as fh:  # 한 건씩 바로 저장
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[e2e] {n}/{len(todo)} {set_id} {row['status']} {row['seconds']}초 호출 {row['model_calls']}번"
              + (f" 오류 {row['error']}" if row["error"] else ""), flush=True)
    print(f"[e2e] 이번 실행 모델 호출 합계 {calls['model']}번")


# ---------------------------------------------------------------------------
# 표 (모델 호출 없음)
# ---------------------------------------------------------------------------
def summarize(rows: list[dict]) -> dict:
    """측정 줄들 → 형식별 숫자. 탐지·읽기 채점은 eval/score.py(2번)의 함수를 그대로 쓴다."""
    from eval.score import load_answers, load_formats, score_detection, score_fields
    from tools.models import ExtractedDocument, Issue

    formats = load_formats()
    issues = {r["set_id"]: [Issue.model_validate(i) for i in r["issues"]] for r in rows if r["status"]}
    docs = {r["set_id"]: [ExtractedDocument.model_validate(d) for d in r["docs"]] for r in rows if r["status"]}
    detection = score_detection(load_answers(), issues, "dev", fmt_by_doc=formats)
    fields = score_fields(EVAL / "fields.csv", docs, fmt_by_doc=formats)
    by_fmt: dict[str, Counter] = defaultdict(Counter)
    seconds: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        fmt_ci = r["formats"].get("commercial_invoice", "?")
        seconds[fmt_ci].append(r["seconds"])
        for name, expected, ok in r["classified"]:
            fmt = r["formats"].get(expected, "?")
            by_fmt[fmt]["분류"] += 1
            by_fmt[fmt]["분류 맞음"] += ok
    hs = Counter(h["status"] for r in rows for h in r["hs"])
    return {
        "sets": len(rows), "status": dict(Counter(r["status"] for r in rows)),
        "model_calls": sum(r["model_calls"] for r in rows),
        "classify_by_format": {f: dict(c) for f, c in sorted(by_fmt.items())},
        "detection": {k: detection[k] for k in ("planted", "detected", "flagged", "normal_sets", "false_positive_sets",
                                                "check_needed_sets", "wrong_cell_sets", "by_format", "by_error_type")},
        "false_positives": detection["false_positives"], "misses": detection["misses"],
        "fields": {k: fields[k] for k in ("docs", "docs_correct", "cells", "cells_correct", "unread", "by_field", "by_format")},
        "hs": dict(hs),
        "seconds_by_ci_format": {f: {"mean": round(statistics.mean(v), 1), "max": max(v)} for f, v in sorted(seconds.items())},
        "seconds": {"mean": round(statistics.mean(r["seconds"] for r in rows), 1), "max": max(r["seconds"] for r in rows)},
    }


def report(out: Path, summary_path: Path | None) -> dict:
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    s = summarize(rows)
    print(json.dumps(s, ensure_ascii=False, indent=1))
    if summary_path is not None:
        summary_path.write_text(json.dumps(s, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[e2e] 표 → {summary_path}")
    return s


def main() -> None:
    parser = argparse.ArgumentParser(description="끝까지 측정 (개발용, FB15 #172)")
    parser.add_argument("--per-format", type=int, default=10, help="상업송장 형식마다 세트 수 (기본 10 → 30세트)")
    parser.add_argument("--sets", nargs="+", help="세트를 직접 고른다. 예: D003 D005")
    parser.add_argument("--out", type=Path, default=OUT, help=f"결과 JSONL (기본 {OUT.relative_to(ROOT)})")
    parser.add_argument("--no-cache", action="store_true", help="로컬 판독 캐시를 쓰지 않는다")
    parser.add_argument("--report", action="store_true", help="모델 호출 없이 결과 파일로 표만 낸다")
    args = parser.parse_args()
    if args.report:
        report(args.out, SUMMARY if args.out == OUT else None)
        return
    set_ids = args.sets or pick_sets(args.per_format)
    measure(set_ids, args.out, None if args.no_cache else CACHE)
    report(args.out, SUMMARY if args.out == OUT else None)


if __name__ == "__main__":
    main()
