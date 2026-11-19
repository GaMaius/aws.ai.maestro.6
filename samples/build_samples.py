"""샘플 서류와 정답지를 만든다.

입력 (사람이 VS Code에서 직접 채운다)
  samples/data/parties.csv  거래처 (수출자·수입자, 모두 가상 값)
  samples/data/items.csv    품목 (정답 HS 10자리 포함)
  samples/data/sets.csv     세트 한 줄 = 화물 한 건. 오류는 PL_ 칸에만 적는다.
양식
  samples/templates/templates.xlsx  (레퍼런스 기반 양식. 이 스크립트는 읽기만 한다)
출력
  samples/<split>/<set_id>/doc_a.(pdf|png), doc_b.(pdf|png)
  eval/sets.csv, eval/fields.csv, eval/answers.csv

이 스크립트는 값을 만들지 않는다. CSV에 적힌 값을 양식에 넣고 PDF로 저장만 한다.
필요한 것: openpyxl, LibreOffice(soffice). PNG가 있으면 poppler(pdftoppm)도.

사용법 (저장소 맨 위에서)
  python samples/build_samples.py
  python samples/build_samples.py --only S01 S02     # 일부 세트만
"""
import argparse, csv, datetime as dt, os, shlex, shutil, subprocess, sys, tempfile
from pathlib import Path
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "samples/templates/templates.xlsx"
DATA = ROOT / "samples/data"
EVAL = ROOT / "eval"
DOC_TYPE = {"CI": "commercial_invoice", "PL": "packing_list"}
# 임시 rule_id. 금요일에 관세 규칙 담당이 정한 ID로 바꾼다.
RULES = {"invoice_no": "X-INV-01", "total_qty": "X-QTY-01", "total_gross_kg": "X-WT-01"}


def find_soffice():
    if os.environ.get("SOFFICE"):
        return shlex.split(os.environ["SOFFICE"])
    for c in ("soffice", "libreoffice"):
        if shutil.which(c):
            return [shutil.which(c)]
    mac = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    if os.path.exists(mac):
        return [mac]
    sys.exit("LibreOffice를 찾지 못했어요. 맥: brew install --cask libreoffice")


def soffice(cmd, fmt, outdir, files):
    """여러 파일을 한 번에 변환한다 (LibreOffice가 수식도 다시 계산한다)."""
    outdir.mkdir(parents=True, exist_ok=True)
    for i in range(0, len(files), 40):
        r = subprocess.run(cmd + ["--headless", "--calc", "--convert-to", fmt, "--outdir", str(outdir)]
                           + [str(f) for f in files[i:i + 40]], capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            sys.exit(f"LibreOffice 변환 실패:\n{r.stderr}")


def read_csv(name):
    with open(DATA / name, encoding="utf-8-sig", newline="") as f:
        return [row for row in csv.DictReader(f) if (row.get(next(iter(row))) or "").strip()]


def typed(header, v):
    v = (v or "").strip()
    if v == "":
        return None
    if header.endswith("_date"):
        return dt.date.fromisoformat(v)
    try:
        return int(v) if v.lstrip("-").isdigit() else float(v)
    except ValueError:
        return v


def fill_sheet(ws, rows):
    hdr = [c.value for c in ws[1] if c.value]
    for r in range(2, ws.max_row + 1):          # 예시 줄 지우기 (서식은 남김)
        for c in range(1, len(hdr) + 1):
            ws.cell(r, c).value = None
    for r, row in enumerate(rows, 2):
        missing = [h for h in row if h not in hdr]
        if missing:
            sys.exit(f"{ws.title}: 양식에 없는 열 {missing}")
        for c, h in enumerate(hdr, 1):
            ws.cell(r, c).value = typed(h, row.get(h))


def check(parties, items, sets):
    errs = []
    pids = {p["party_id"] for p in parties}
    codes = {i["item_code"] for i in items}
    seen = set()
    for s in sets:
        sid = s["set_id"]
        if sid in seen: errs.append(f"{sid}: set_id 중복")
        seen.add(sid)
        if s["split"] not in ("dev", "test"): errs.append(f"{sid}: split은 dev/test")
        if s["style"] not in ("1", "2"): errs.append(f"{sid}: style은 1/2")
        if s["doc_a"] not in ("CI", "PL"): errs.append(f"{sid}: doc_a는 CI/PL")
        if s["format"] not in ("pdf", "png"): errs.append(f"{sid}: format은 pdf/png")
        for k in ("exporter_id", "consignee_id"):
            if s[k] not in pids: errs.append(f"{sid}: {k} '{s[k]}'가 parties.csv에 없음")
        if not s["item1_code"]: errs.append(f"{sid}: item1_code 비어 있음")
        for i in (1, 2, 3):
            c = s[f"item{i}_code"]
            if c and c not in codes: errs.append(f"{sid}: item{i}_code '{c}'가 items.csv에 없음")
            if c and not s[f"item{i}_qty"]: errs.append(f"{sid}: item{i}_qty 비어 있음")
    for i in items:
        if not i["hs10_answer"]:
            print(f"  주의: {i['item_code']}의 정답 HS(hs10_answer)가 비어 있어요")
    if errs:
        sys.exit("입력 오류:\n  " + "\n  ".join(errs))


def r2(x):
    if x in (None, ""):
        return None
    v = round(float(x), 2)
    return int(v) if v == int(v) else v


def write_eval(calc, sets_rows):
    """계산 시트 값으로 정답지 세 개를 만든다."""
    hdr = [c.value for c in calc[1]]
    by_id = {}
    for r in range(2, calc.max_row + 1):
        row = {h: calc.cell(r, i + 1).value for i, h in enumerate(hdr) if h}
        if row.get("set_id"):
            by_id[row["set_id"]] = row
    EVAL.mkdir(exist_ok=True)
    s_out, f_out, a_out = [], [], []
    for s in sets_rows:
        sid, k = s["set_id"], by_id.get(s["set_id"])
        if k is None:
            sys.exit(f"{sid}: 계산 값을 못 읽었어요")
        b = "PL" if s["doc_a"] == "CI" else "CI"
        docs = f"doc_a={DOC_TYPE[s['doc_a']]};doc_b={DOC_TYPE[b]};format={s['format']};style={s['style']}"
        for i in (1, 2, 3):
            if k.get(f"code{i}"):
                s_out.append([sid, s["split"], k["con_name"], docs, i, k[f"desc{i}"], k.get(f"hs{i}") or ""])
        for doc, pre in (("commercial_invoice", "ci"), ("packing_list", "pl")):
            f_out += [[sid, doc, "invoice_no", k[f"{pre}_invoice_no"]],
                      [sid, doc, "total_qty", k[f"{pre}_total_qty"]],
                      [sid, doc, "total_gross_kg", r2(k[f"{pre}_total_gross"])],
                      [sid, doc, "exporter_name", k["exp_name"]],
                      [sid, doc, "consignee_name", k["con_name"]]]
        planted = []
        for field, ci, pl in (("invoice_no", k["ci_invoice_no"], k["pl_invoice_no"]),
                              ("total_qty", r2(k["ci_total_qty"]), r2(k["pl_total_qty"])),
                              ("total_gross_kg", r2(k["ci_total_gross"]), r2(k["pl_total_gross"]))):
            if ci != pl:
                planted.append([sid, s["split"], "packing_list", field, pl, ci, "value_change", RULES[field]])
        a_out += planted or [[sid, s["split"], "", "", "", "", "none", ""]]
    for name, head, rows in (
            ("sets.csv", ["set_id", "split", "consignee", "docs", "line", "item", "hs_answer"], s_out),
            ("fields.csv", ["set_id", "doc", "field", "answer"], f_out),
            ("answers.csv", ["set_id", "split", "doc", "field", "planted_value", "original_value", "error_type", "expected_rule_id"], a_out)):
        with open(EVAL / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(head); w.writerows(rows)
    return sum(1 for a in a_out if a[6] != "none"), sum(1 for a in a_out if a[6] == "none")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="이 세트만 서류를 만든다 (정답지는 항상 전체)")
    args = ap.parse_args()
    cmd = find_soffice()
    parties, items, sets = read_csv("parties.csv"), read_csv("items.csv"), read_csv("sets.csv")
    check(parties, items, sets)
    print(f"거래처 {len(parties)}, 품목 {len(items)}, 세트 {len(sets)}")

    work = Path(tempfile.mkdtemp(prefix="samples_"))
    wb = load_workbook(TEMPLATE)
    fill_sheet(wb["거래처"], parties); fill_sheet(wb["품목"], items); fill_sheet(wb["세트"], sets)
    targets = [s for s in sets if not args.only or s["set_id"] in args.only]

    # 1) 세트마다 안내!C4를 바꾼 사본을 만들고 LibreOffice로 다시 계산한다
    filled = []
    for s in targets:
        wb["안내"]["C4"] = s["set_id"]
        p = work / "filled" / f"{s['set_id']}.xlsx"; p.parent.mkdir(exist_ok=True)
        wb.save(p); filled.append(p)
    if not filled:
        wb["안내"]["C4"] = sets[0]["set_id"]; p = work / "filled" / "all.xlsx"; p.parent.mkdir(exist_ok=True)
        wb.save(p); filled.append(p)
    soffice(cmd, "xlsx", work / "calc", filled)

    # 2) 정답지 (계산 시트는 C4와 무관하니 첫 파일로 충분)
    first = load_workbook(work / "calc" / filled[0].name, data_only=True)
    n_err, n_ok = write_eval(first["계산"], sets)
    print(f"정답지: 심은 오류 {n_err}건, 정상 세트 {n_ok}개 → eval/answers.csv, fields.csv, sets.csv")

    # 3) 서류 한 장 = 시트 하나만 남긴 파일 → PDF
    singles, plan = [], []
    for s in targets:
        for slot, kind in (("doc_a", s["doc_a"]), ("doc_b", "PL" if s["doc_a"] == "CI" else "CI")):
            sheet = f"{kind}_{s['style']}"
            v = load_workbook(work / "calc" / f"{s['set_id']}.xlsx", data_only=True)
            for ws in list(v.worksheets):
                if ws.title != sheet:
                    v.remove(ws)
            v[sheet]["K1"] = v[sheet]["K2"] = v[sheet]["K3"] = None     # 인쇄 영역 밖 확인용 칸 비우기
            p = work / "single" / f"{s['set_id']}__{slot}.xlsx"; p.parent.mkdir(exist_ok=True)
            v.save(p); singles.append(p); plan.append((s, slot, p.stem))
    soffice(cmd, "pdf", work / "pdf", singles)

    # 4) 제자리에 저장. png면 pdftoppm으로 바꾼다
    pdftoppm = shutil.which("pdftoppm")
    for s, slot, stem in plan:
        dest = ROOT / "samples" / s["split"] / s["set_id"]; dest.mkdir(parents=True, exist_ok=True)
        pdf = work / "pdf" / f"{stem}.pdf"
        if s["format"] == "png":
            if not pdftoppm:
                sys.exit("png 변환에 pdftoppm이 필요해요. 맥: brew install poppler")
            subprocess.run([pdftoppm, "-r", "150", "-png", "-singlefile", str(pdf), str(dest / slot)], check=True)
        else:
            shutil.copy(pdf, dest / f"{slot}.pdf")
    shutil.rmtree(work, ignore_errors=True)
    print(f"서류 {len(plan)}장 → samples/dev, samples/test")
    if any(s["split"] == "test" for s in targets):
        print("주의: samples/test 는 오늘 밤 커밋하지 마세요 (.gitignore에 samples/test/ 추가 권장)")


if __name__ == "__main__":
    main()
