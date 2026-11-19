"""데이터셋 입력 검사와 만든 서류 확인. 읽기만 하고 값은 고치지 않는다 (--lock-test 만 잠금 파일을 쓴다).

사용법 (저장소 맨 위에서)
  .venv/bin/python samples/check_samples.py                    입력 검사 + 진행 현황 + 발표용 잠금 확인 (몇 초)
  .venv/bin/python samples/check_samples.py --docs             + 정답 값이 찍혔는지, 품명이 끝까지 보이는지 (1~3분)
  .venv/bin/python samples/check_samples.py --docs --only D003 T010
  .venv/bin/python samples/check_samples.py --lock-test        발표용 세트를 잠근다 (samples/test_lock.json 을 커밋하고 태그)

값 확인: PDF는 글자층(pdftotext), PNG는 OCR(tesseract)로 정답지와 비교한다.
품명 확인: 서류를 그림으로 그려 OCR로 품명의 처음과 끝이 보이는지 본다. 칸 밖으로 잘린 글자도
PDF 글자층에는 남아 있어서, 글자층만 보면 잘린 것을 못 잡는다.
"""
import argparse, contextlib, csv, difflib, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_samples as kit  # noqa: E402  키트의 CSV 읽기와 검사를 그대로 쓴다

ROOT, EVAL, EVAL_TEST = kit.ROOT, kit.EVAL, kit.EVAL_TEST
TEST_SETS, LOCK_FILE = kit.TEST_SETS, kit.LOCK_FILE
EVAL_NAMES = ("answers.csv", "fields.csv", "sets.csv")
GOAL_SETS, GOAL_TEST_ERR, GOAL_TEST_OK = 125, 20, 10   # 팀 계획 문서의 목표
TITLE = {"commercial_invoice": "COMMERCIALINVOICE", "packing_list": "PACKINGLIST"}
SHORT = {"commercial_invoice": "CI", "packing_list": "PL"}


def val(row, key):
    return (row.get(key) or "").strip()


def num(v):
    try:
        float(v)
        return True
    except ValueError:
        return False


def read_sets():
    """개발용(sets.csv)과 발표용(sets_test.csv, 있으면) 입력."""
    return kit.read_csv("sets.csv") + (kit.read_csv("sets_test.csv") if TEST_SETS.exists() else [])


def read_eval(name, split=None):
    rows = []
    for s, folder in (("dev", EVAL), ("test", EVAL_TEST)):
        if (split in (None, s)) and (folder / name).exists():
            with open(folder / name, encoding="utf-8", newline="") as f:
                rows += list(csv.DictReader(f))
    return rows


def fresh():
    """분할마다 정답지가 입력보다 나중에 만들어졌는지. 발표용은 sets_test.csv 하고만 비교한다
    (잠근 뒤에는 카탈로그가 바뀌어도 발표용을 다시 만들지 않으므로)."""
    dev_in = max((kit.DATA / n).stat().st_mtime for n in ("parties.csv", "items.csv", "sets.csv"))
    out = {"dev": all((EVAL / n).exists() and (EVAL / n).stat().st_mtime >= dev_in for n in EVAL_NAMES)}
    if TEST_SETS.exists():
        out["test"] = all((EVAL_TEST / n).exists() and (EVAL_TEST / n).stat().st_mtime >= TEST_SETS.stat().st_mtime
                          for n in EVAL_NAMES)
    return out


def planted(s):
    """입력 한 줄에서 심은 P0 오류 칸을 추정한다. 정확한 값은 서류를 만든 뒤 정답지."""
    out = []
    if val(s, "PL_invoice_no") and val(s, "PL_invoice_no") != val(s, "invoice_no"):
        out.append("invoice_no")
    if any(num(val(s, f"PL_qty{n}")) and num(val(s, f"item{n}_qty"))
           and float(val(s, f"PL_qty{n}")) != float(val(s, f"item{n}_qty")) for n in (1, 2, 3)):
        out.append("total_qty")
    if any(val(s, f"PL_gross{n}") for n in (1, 2, 3)):
        out.append("total_gross_kg")
    return out


# ── 입력 검사 ────────────────────────────────────────────────────────────────
def check_inputs():
    parties, items, sets = kit.read_csv("parties.csv"), kit.read_csv("items.csv"), read_sets()
    errs, warns = [], []
    try:
        with contextlib.redirect_stdout(io.StringIO()):   # HS 빈칸 안내는 진행 현황에서 한 줄로
            kit.check(parties, items, sets)
    except SystemExit as e:
        errs += [line.strip() for line in str(e.code).splitlines()[1:] if line.strip()]

    unit = {i["item_code"]: val(i, "unit") for i in items}
    country = {p["party_id"]: val(p, "country") for p in parties}
    po_seen, inv_seen = {}, {}
    for i in items:
        for k in ("unit_price_usd", "net_kg_per_unit", "units_per_ctn", "ctn_tare_kg", "cbm_per_ctn"):
            if val(i, k) and not num(val(i, k)):
                errs.append(f"품목 {i['item_code']}: {k} '{val(i, k)}'가 숫자가 아님")
    all_inv = {val(s, "invoice_no") for s in sets}
    for s in sets:
        sid, term = val(s, "set_id"), val(s, "incoterms").split(" ", 1)
        if len(term) == 2:                                                       # G4
            want = {"FOB": val(s, "port_loading"), "CFR": val(s, "port_discharge"),
                    "CIF": val(s, "port_discharge")}.get(term[0], "").split(",")[0]
            if want and term[1] != want:
                warns.append(f"{sid}: 인코텀즈 {val(s, 'incoterms')}의 지정 장소가 {want}가 아님 (G4)")
        for k in ("invoice_date", "sailing_date"):
            if val(s, k):
                try:
                    date.fromisoformat(val(s, k))
                except ValueError:
                    errs.append(f"{sid}: {k} '{val(s, k)}'는 YYYY-MM-DD 형식이 아님")
        try:                                                                     # G6
            if date.fromisoformat(val(s, "sailing_date")) < date.fromisoformat(val(s, "invoice_date")):
                warns.append(f"{sid}: 선적일이 송장일보다 빠름 (G6)")
        except ValueError:
            pass
        exp_c = country.get(val(s, "exporter_id"), "")                           # G10
        if val(s, "origin") and exp_c and val(s, "origin") != exp_c:
            warns.append(f"{sid}: 원산지 {val(s, 'origin')}가 수출국 {exp_c}와 다름 (G10)")
        for key, seen, label in (("po_no", po_seen, "po_no"), ("invoice_no", inv_seen, "invoice_no")):   # G9
            v = val(s, key)
            if v and v in seen:
                warns.append(f"{sid}: {label} '{v}'가 {seen[v]}와 같음 (G9)")
            elif v:
                seen[v] = sid
        if val(s, "PL_invoice_no") and val(s, "PL_invoice_no") != val(s, "invoice_no") \
                and val(s, "PL_invoice_no") in all_inv:                          # E: 다른 세트 번호와 겹침
            warns.append(f"{sid}: 심은 송장 번호 '{val(s, 'PL_invoice_no')}'가 다른 세트의 진짜 번호와 같음")
        for n in (1, 2, 3):
            for k in (f"item{n}_qty", f"PL_qty{n}", f"PL_gross{n}"):
                if val(s, k) and not num(val(s, k)):
                    errs.append(f"{sid}: {k} '{val(s, k)}'가 숫자가 아님")
            for k in (f"PL_qty{n}", f"PL_gross{n}"):
                if val(s, k) and not val(s, f"item{n}_code"):
                    warns.append(f"{sid}: {k}에 값이 있는데 item{n}_code가 비어 있음")
            if num(val(s, f"PL_qty{n}")) and num(val(s, f"item{n}_qty")) \
                    and float(val(s, f"PL_qty{n}")) == float(val(s, f"item{n}_qty")):
                warns.append(f"{sid}: PL_qty{n}이 item{n}_qty와 같아서 오류가 심기지 않음")
        if val(s, "PL_invoice_no") and val(s, "PL_invoice_no") == val(s, "invoice_no"):
            warns.append(f"{sid}: PL_invoice_no가 invoice_no와 같아서 오류가 심기지 않음")
        units = {unit[c] for c in (val(s, f"item{n}_code") for n in (1, 2, 3)) if c in unit}
        if len(units) > 1:
            warns.append(f"{sid}: 한 세트 안 품목 단위가 다름 {sorted(units)} (총수량 비교가 의미 없어짐)")
        for k in ("CI_total_amount_ovr", "PL_total_gross_ovr"):
            if val(s, k):
                warns.append(f"{sid}: {k}는 P1용이라 지금은 비워 두기로 함")
    no_hs = [i["item_code"] for i in items if not val(i, "hs10_answer")]
    return parties, items, sets, errs, warns, no_hs


def progress(parties, items, sets, no_hs):
    is_fresh = fresh()
    n_split = Counter(val(s, "split") for s in sets)
    print("\n진행 현황")
    print(f"  세트 {len(sets)} / 목표 약 {GOAL_SETS}  (dev {n_split['dev']}, test {n_split['test']})"
          f" · 거래처 {len(parties)} · 품목 {len(items)}")
    for split in ("dev", "test"):
        ok, errc = 0, Counter()
        if is_fresh.get(split):
            src = "정답지"
            for a in read_eval("answers.csv", split):
                if a["error_type"] == "none":
                    ok += 1
                else:
                    errc[a["field"]] += 1
        else:
            src = "입력 추정"
            for s in sets:
                if val(s, "split") == split:
                    p = planted(s)
                    errc.update(p)
                    ok += not p
        detail = ", ".join(f"{k} {v}" for k, v in sorted(errc.items())) or "-"
        if split == "test":
            print(f"  test: 정상 {ok} / {GOAL_TEST_OK}, 심은 오류 {sum(errc.values())} / {GOAL_TEST_ERR}  ({detail}) [{src}]")
        else:
            print(f"  dev : 정상 {ok}, 심은 오류 {sum(errc.values())}  ({detail}) [{src}]")

    def mix(k):
        return " ".join(f"{v}:{c}" for v, c in sorted(Counter(val(s, k) for s in sets).items()))
    print(f"  섞임: style {mix('style')} · format {mix('format')} · doc_a {mix('doc_a')}")
    print(f"  정답 HS 빈 품목 {len(no_hs)} / {len(items)}" + ("  (HS 추천은 P1이라 나중에 채워도 됨)" if no_hs else ""))


# ── 발표용 잠금 ──────────────────────────────────────────────────────────────
def lock_targets():
    files = [TEST_SETS] + [EVAL_TEST / n for n in EVAL_NAMES]
    files += sorted((ROOT / "samples" / "test").glob("*/doc_*"))
    return [f for f in files if f.exists()]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lock_test():
    files = lock_targets()
    if not TEST_SETS.exists() or not (EVAL_TEST / "answers.csv").exists() \
            or not any(f.name.startswith("doc_") for f in files):
        sys.exit("발표용 입력·정답지·서류가 모두 있어야 잠글 수 있어요 (generate_dataset.py → build_samples.py --test)")
    data = {"locked_at": datetime.now().isoformat(timespec="seconds"),
            "note": "발표용 세트의 해시만 적는다. 값과 정답은 git에 올리지 않는다.",
            "files": {str(f.relative_to(ROOT)): sha(f) for f in files}}
    LOCK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"발표용 세트를 잠갔어요: 파일 {len(files)}개 → {LOCK_FILE.relative_to(ROOT)}")
    print("  이 파일을 커밋하고 태그를 다세요 (예: git tag test-lock-v1). 이후 발표용을 다시 만들면 여기서 잡혀요.")


def verify_lock():
    if not LOCK_FILE.exists():
        print("\n발표용 잠금: 아직 안 잠김 (확인 뒤 --lock-test)")
        return 0
    locked = json.loads(LOCK_FILE.read_text(encoding="utf-8"))["files"]
    now = {str(f.relative_to(ROOT)): sha(f) for f in lock_targets()}
    changed = [p for p, h in locked.items() if now.get(p) != h]
    added = [p for p in now if p not in locked]
    if not changed and not added:
        print(f"\n발표용 잠금: 그대로 (파일 {len(locked)}개)")
        return 0
    print(f"\n발표용 잠금이 깨졌어요: 바뀌거나 없어진 파일 {len(changed)}개, 새 파일 {len(added)}개")
    for p in (changed + added)[:10]:
        print(f"  - {p}")
    return 1


# ── 서류 확인 ────────────────────────────────────────────────────────────────
def alnum(t):
    return re.sub(r"[^0-9A-Z]", "", t.upper())


def found(answer, text):
    a = answer.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", a):          # 숫자: 천 단위 쉼표와 뒤쪽 0을 무시 (1270 = 1,270.00)
        ip, _, dp = a.partition(".")
        pat = rf"(?<![\d.]){re.escape(ip)}" + (rf"\.{dp}0*" if dp else r"(?:\.0+)?") + r"(?!\.?\d)"
        return re.search(pat, text.replace(",", "")) is not None
    return alnum(a) in alnum(text)                   # 글자: 띄어쓰기와 문장부호를 무시


def fuzzy_in(needle, hay, cutoff=0.85):
    """OCR 오타를 조금 봐준다: 같은 길이 구간과 85% 이상 같으면 있는 것으로 본다."""
    if needle in hay:
        return True
    n = len(needle)
    return any(difflib.SequenceMatcher(None, needle, hay[i:i + n]).ratio() >= cutoff
               for i in range(max(1, len(hay) - n + 1)))


OCR_LOOKALIKE = str.maketrans("OILSBZ", "011582")    # OCR이 헷갈리는 글자 (40W → 4OW 등)


def hidden_words(desc, seen_alnum):
    """품명 낱말(3자 이상) 중 그림 OCR에 안 보이는 것. 품명이 여러 줄로 꺾이면 OCR이 옆 칸 글자를
    줄 사이에 끼워 넣어서, 품명 전체가 아니라 낱말 단위로 본다. 잘린 줄은 낱말째로 사라져서 잡힌다."""
    t = seen_alnum.translate(OCR_LOOKALIKE)
    out = []
    for w in re.findall(r"[A-Z0-9]+", desc.upper()):
        k = w.translate(OCR_LOOKALIKE)
        if len(w) >= 3 and k not in t and not (len(k) >= 5 and fuzzy_in(k, t, 0.8)):
            out.append(w)
    return out


def ocr(png):
    # 표 테두리 때문에 기본 모드(psm 3)가 칸 글자를 빠뜨려서, 흩어진 글자 모드(psm 11)와 합친다
    return "\n".join(subprocess.run(["tesseract", str(png), "-", "-l", "eng", "--psm", psm],
                                    capture_output=True, text=True).stdout for psm in ("3", "11"))


def read_doc(path):
    """(값 확인용 글자, 그림 OCR 글자). PDF는 글자층과 그림 둘 다, PNG는 그림만."""
    if path.suffix == ".png":
        t = ocr(path)
        return t, t
    layer = "\n".join(subprocess.run(["pdftotext", *opt, str(path), "-"], capture_output=True, text=True).stdout
                      for opt in (["-layout"], []))
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "150", "-png", "-singlefile", str(path), f"{tmp}/page"], check=True)
        return layer, ocr(Path(tmp) / "page.png")


def line_qtys():
    """세트별 서류 줄 수량. 스타일 2 상업송장은 줄이 여럿이면 총수량을 찍지 않아서, 줄 수량으로 확인한다."""
    out = {}
    for s in read_sets():
        codes = [n for n in (1, 2, 3) if val(s, f"item{n}_code")]
        out[val(s, "set_id")] = {"commercial_invoice": [val(s, f"item{n}_qty") for n in codes],
                                 "packing_list": [val(s, f"PL_qty{n}") or val(s, f"item{n}_qty") for n in codes]}
    return out


def check_docs(only):
    if not read_eval("fields.csv"):
        print("\n정답지가 없어요. 먼저 서류를 만드세요: .venv/bin/python samples/build_samples.py")
        return 1
    stale = [s for s, ok in fresh().items() if not ok]
    if stale:
        print(f"\n주의: {', '.join(stale)} 입력이 서류를 마지막으로 만든 뒤에 바뀌었어요. 다시 만든 뒤 확인하세요.")
    if not shutil.which("tesseract"):
        print("\n주의: tesseract가 없어 PNG 값 확인과 품명 확인을 건너뜀 (brew install tesseract)")
    meta, answers, descs = {}, {}, {}
    for r in read_eval("sets.csv"):
        meta.setdefault(r["set_id"], (r["split"], dict(kv.split("=", 1) for kv in r["docs"].split(";"))))
        descs.setdefault(r["set_id"], []).append(r["item"])
    for r in read_eval("fields.csv"):
        answers.setdefault(r["set_id"], []).append(r)
    lines = line_qtys()

    jobs = []
    for sid, (split, d) in meta.items():
        if only and sid not in only:
            continue
        for slot in ("doc_a", "doc_b"):
            jobs.append((sid, split, d, slot, ROOT / "samples" / split / sid / f"{slot}.{d['format']}"))
    has_ocr = shutil.which("tesseract") is not None
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:      # OCR이 느려서 나눠 돌린다
        texts = list(pool.map(lambda j: read_doc(j[4]) if j[4].exists() and has_ocr else (None, None), jobs))

    bad, notes, rows = 0, [], {}
    n_desc = n_desc_ok = 0
    for (sid, split, d, slot, path), (text, seen) in zip(jobs, texts):
        kind, rel = d[slot], path.relative_to(ROOT)
        label = f"{slot}({SHORT[kind]}·{d['format']})"
        if not path.exists():
            rows.setdefault(sid, []).append(f"{label} 없음")
            notes.append(f"{sid} {slot}: 서류 파일이 없음 → 서류 만들기 필요 ({rel})")
            bad += 1
            continue
        if text is None:
            rows.setdefault(sid, []).append(f"{label} 건너뜀")
            continue
        want = [r for r in answers.get(sid, []) if r["doc"] == kind and r["answer"].strip()]
        if not want:
            rows.setdefault(sid, []).append(f"{label} 정답 없음")
            notes.append(f"{sid} {slot}: 정답지에 이 서류의 정답 값이 없음 → 서류를 다시 만드세요")
            bad += 1
            continue
        line_q = lines.get(sid, {}).get(kind, [])
        miss = [r for r in want if not found(r["answer"], text)
                and not (r["field"] == "total_qty" and len(line_q) > 1      # 총수량 대신 줄 수량이 모두 찍혔으면 OK
                         and all(found(q, text) for q in line_q)
                         and sum(float(q) for q in line_q) == float(r["answer"]))]
        extra = [x for x, key in (("SAMPLE 문구", "SAMPLEFORTESTINGONLY"), (f"제목({SHORT[kind]})", TITLE[kind]))
                 if key not in alnum(text)]
        hidden, seen_alnum = [], alnum(seen)                  # 품명 낱말이 그림에 다 보이는지
        for desc in descs.get(sid, []):
            n_desc += 1
            gone = hidden_words(desc, seen_alnum)
            if gone:
                hidden.append(f"{desc} (안 보임: {' '.join(gone)})")
            else:
                n_desc_ok += 1
        ok = not miss and not extra and not hidden
        rows.setdefault(sid, []).append(f"{label} {'OK' if ok else '확인 필요'} {len(want) - len(miss)}/{len(want)}")
        notes += [f"{sid} {slot}: {r['field']} '{r['answer']}'를 서류에서 못 찾음" for r in miss]
        notes += [f"{sid} {slot}: {x}를 서류에서 못 찾음" for x in extra]
        notes += [f"{sid} {slot}: 품명이 잘렸을 수 있음 '{h}' → 눈으로 확인: {rel}" for h in hidden]
        bad += len(hidden)                                   # 품명은 그림으로 봐야 해서 PDF·PNG 모두 실패로 센다
        if (miss or extra) and path.suffix == ".png":
            notes.append(f"  └ PNG 값은 OCR이라 잘못 읽었을 수 있어요. 눈으로 확인: {rel}")
        elif miss or extra:
            bad += 1
    print("\n서류 확인 (정답 값이 찍혔는지, 품명이 끝까지 보이는지)")
    for sid, cells in rows.items():
        print(f"  {sid}  " + "   ".join(cells))
    print(f"  품명 보임: {n_desc_ok} / {n_desc}")
    for n in notes:
        print(f"  - {n}" if not n.startswith("  └") else f"  {n}")
    print("  모두 정상이에요." if not notes else "")
    return bad


def main():
    ap = argparse.ArgumentParser(description="데이터셋 입력 검사와 서류 확인")
    ap.add_argument("--docs", action="store_true", help="만든 서류에 정답 값이 찍혔는지, 품명이 보이는지도 확인")
    ap.add_argument("--only", nargs="*", help="서류 확인을 이 세트만 (예: --only D003 T010)")
    ap.add_argument("--lock-test", action="store_true", help="발표용 세트를 잠근다 (samples/test_lock.json)")
    args = ap.parse_args()
    if args.lock_test:
        lock_test()
        return

    parties, items, sets, errs, warns, no_hs = check_inputs()
    print("입력 검사 (samples/data/*.csv)")
    for e in errs:
        print(f"  오류  {e}")
    for w in warns:
        print(f"  주의  {w}")
    if not errs and not warns:
        print("  문제 없음")
    progress(parties, items, sets, no_hs)
    bad = verify_lock()
    bad += check_docs(args.only) if args.docs else 0
    sys.exit(1 if errs or bad else 0)


if __name__ == "__main__":
    main()
