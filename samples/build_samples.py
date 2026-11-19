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
import argparse, csv, datetime as dt, os, re, shlex, shutil, subprocess, sys, tempfile
from copy import copy
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator
from openpyxl.utils import get_column_letter

# error_note 안의 [칸:오류종류] 표시 (생성기가 적는다). 없으면 정답지 error_type은 value_change
ERROR_TAG = re.compile(r"\[(\w+):(\w+)\]")

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "samples/templates/templates.xlsx"
DATA = ROOT / "samples/data"
EVAL = ROOT / "eval"
DOC_TYPE = {"CI": "commercial_invoice", "PL": "packing_list"}
# 임시 rule_id. 금요일에 관세 규칙 담당이 정한 ID로 바꾼다.
RULES = {"invoice_no": "X-INV-01", "total_qty": "X-QTY-01", "total_gross_kg": "X-WT-01"}
# 발표용 세트: 입력과 정답지를 git에 올리지 않는 곳에 따로 두고, 잠금 파일(해시)로 고정한다
TEST_SETS, EVAL_TEST, LOCK_FILE = DATA / "sets_test.csv", EVAL / "test", ROOT / "samples/test_lock.json"
DOC_SHEETS = ("CI_1", "PL_1", "CI_2", "PL_2")
DESC_REF = {"X": 1, "AK": 2, "AX": 3}           # 계산 시트의 품명 열 (desc1·desc2·desc3)


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
    if header.startswith("hs"):                 # HS는 글자로 둔다 (0901.11 → 901.11 이 되지 않게)
        return v
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


def extend_calc(ws, n_sets):
    """계산 시트 수식을 세트 수만큼 아래로 늘린다. 양식에는 60세트(2~61행)까지만 있다.
    서류 시트는 계산 시트를 열 전체로 읽으므로 수식만 늘리면 된다."""
    last = 1
    while str(ws.cell(last + 1, 1).value or "").startswith("="):
        last += 1
    for r in range(last + 1, n_sets + 2):
        for c in range(1, ws.max_column + 1):
            src = ws.cell(last, c).value
            if isinstance(src, str) and src.startswith("="):
                ws.cell(r, c).value = Translator(src, origin=ws.cell(last, c).coordinate).translate_formula(
                    ws.cell(r, c).coordinate)


def desc_layout(wb):
    """서류 시트마다 품명 칸 위치와 한 줄 글자 수, 줄 높이를 잰다. {시트: {줄: (칸, 한 줄 글자 수, 줄 높이pt)}}
    한 줄 글자 수는 실제보다 적게 잡는다(행이 조금 넉넉해질 뿐 글자가 잘리지는 않게)."""
    out = {}
    for name in DOC_SHEETS:
        ws = wb[name]
        for row in ws.iter_rows():
            for c in row:
                m = isinstance(c.value, str) and re.search(r"계산!\$(X|AK|AX):", c.value)
                if not m:
                    continue
                rng = next((r for r in ws.merged_cells.ranges if c.coordinate in r), None)
                cols = range(rng.min_col, rng.max_col + 1) if rng else [c.column]
                width = sum(ws.column_dimensions[get_column_letter(i)].width or 8.43 for i in cols)
                size = float(c.font.sz or 10)
                if "courier" in (c.font.name or "").lower():          # 고정폭: 글자 하나 = 0.6em
                    cpl = int((width * 5.25 - 4) / (0.6 * size)) - 1
                else:                                                # 비례폭(Arial): 대문자 기준
                    cpl = int(width * 8.4 / size)
                out.setdefault(name, {})[DESC_REF[m.group(1)]] = (c.coordinate, cpl, size * 1.3)
    return out


def wrapped_lines(text, cpl):
    """띄어쓰기에서 줄을 바꿀 때 몇 줄이 되는지 센다."""
    lines, cur = 1, 0
    for word in str(text).split():
        if cur == 0:
            cur = len(word)
        elif cur + 1 + len(word) <= cpl:
            cur += 1 + len(word)
        else:
            lines, cur = lines + 1, len(word)
        while cur > cpl:                        # 한 줄보다 긴 낱말은 다음 줄로 넘어간다
            lines, cur = lines + 1, cur - cpl
    return lines


def fit_descriptions(ws, cells):
    """품명이 몇 줄로 꺾일지 세어 그 행을 높인다(줄바꿈도 켠다). 양식의 고정 높이로는 2~3줄만 보여 잘렸다."""
    for coord, cpl, line_h in cells.values():
        c = ws[coord]
        if not c.value:
            continue
        al = copy(c.alignment)
        al.wrap_text = True
        c.alignment = al
        need = wrapped_lines(c.value, cpl) * line_h + 4
        rd = ws.row_dimensions[c.row]
        if (rd.height or 15) < need:
            rd.height = round(need, 1)


def pdf_pages(pdf_dir):
    """한 장을 넘는 PDF. PNG는 첫 장만 그리므로, 넘치면 내용이 말없이 사라진다."""
    if not shutil.which("pdfinfo"):
        print("  주의: pdfinfo(poppler)가 없어 쪽수 검사를 건너뜀")
        return []
    over = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        m = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout)
        if m and int(m.group(1)) > 1:
            over.append(f"{pdf.stem}({m.group(1)}쪽)")
    return over


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


def printed_item(i):
    """서류에 찍을 품목 줄. hs_on_invoice 칸이 있으면 송장 HS 칸에 그 값(6자리·10자리·빈칸)을 찍고,
    정답 HS(hs10_answer)는 정답지에만 쓴다. 칸이 없으면 예전처럼 정답 HS를 그대로 찍는다."""
    row = {k: v for k, v in i.items() if k != "hs_on_invoice"}
    if "hs_on_invoice" in i:
        row["hs10_answer"] = i["hs_on_invoice"]
    return row


def write_eval(calc, sets_rows, items):
    """계산 시트 값으로 정답지 세 개를 만든다. 개발용은 eval/, 발표용은 eval/test/ (git에 올리지 않음)."""
    hs_answer = {i["item_code"]: (i.get("hs10_answer") or "").strip() for i in items}
    hdr = [c.value for c in calc[1]]
    by_id = {}
    for r in range(2, calc.max_row + 1):
        row = {h: calc.cell(r, i + 1).value for i, h in enumerate(hdr) if h}
        if row.get("set_id"):
            by_id[row["set_id"]] = row
    outs = {}
    for s in sets_rows:
        sid, k = s["set_id"], by_id.get(s["set_id"])
        if k is None:
            sys.exit(f"{sid}: 계산 값을 못 읽었어요")
        s_out, f_out, a_out = outs.setdefault(s["split"], ([], [], []))
        b = "PL" if s["doc_a"] == "CI" else "CI"
        docs = f"doc_a={DOC_TYPE[s['doc_a']]};doc_b={DOC_TYPE[b]};format={s['format']};style={s['style']}"
        for i in (1, 2, 3):
            if k.get(f"code{i}"):
                s_out.append([sid, s["split"], k["con_name"], docs, i, k[f"desc{i}"], hs_answer.get(k[f"code{i}"], "")])
        for doc, pre in (("commercial_invoice", "ci"), ("packing_list", "pl")):
            f_out += [[sid, doc, "invoice_no", k[f"{pre}_invoice_no"]],
                      [sid, doc, "total_qty", k[f"{pre}_total_qty"]],
                      [sid, doc, "total_gross_kg", r2(k[f"{pre}_total_gross"])],
                      [sid, doc, "exporter_name", k["exp_name"]],
                      [sid, doc, "consignee_name", k["con_name"]]]
        planted = []
        kinds = dict(ERROR_TAG.findall(s.get("error_note") or ""))
        for field, ci, pl in (("invoice_no", k["ci_invoice_no"], k["pl_invoice_no"]),
                              ("total_qty", r2(k["ci_total_qty"]), r2(k["pl_total_qty"])),
                              ("total_gross_kg", r2(k["ci_total_gross"]), r2(k["pl_total_gross"]))):
            if ci != pl:
                planted.append([sid, s["split"], "packing_list", field, pl, ci,
                                kinds.get(field, "value_change"), RULES[field]])
        a_out += planted or [[sid, s["split"], "", "", "", "", "none", ""]]
    counts = {}
    for split, (s_out, f_out, a_out) in outs.items():
        folder = EVAL_TEST if split == "test" else EVAL
        folder.mkdir(parents=True, exist_ok=True)
        for name, head, rows in (
                ("sets.csv", ["set_id", "split", "consignee", "docs", "line", "item", "hs_answer"], s_out),
                ("fields.csv", ["set_id", "doc", "field", "answer"], f_out),
                ("answers.csv", ["set_id", "split", "doc", "field", "planted_value", "original_value", "error_type", "expected_rule_id"], a_out)):
            with open(folder / name, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f); w.writerow(head); w.writerows(rows)
        counts[split] = (sum(1 for a in a_out if a[6] != "none"), sum(1 for a in a_out if a[6] == "none"))
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="이 세트만 서류를 만든다 (정답지는 항상 전체)")
    ap.add_argument("--test", action="store_true", help="발표용 세트(data/sets_test.csv)도 서류와 정답지(eval/test/)를 만든다")
    ap.add_argument("--force-test", action="store_true", help="잠긴 발표용 세트도 다시 만든다 (잠금이 깨진다)")
    args = ap.parse_args()
    cmd = find_soffice()
    parties, items, sets = read_csv("parties.csv"), read_csv("items.csv"), read_csv("sets.csv")
    if args.test:
        if not TEST_SETS.exists():
            sys.exit("발표용 세트 파일이 없어요 (samples/data/sets_test.csv). 먼저 generate_dataset.py 를 돌리세요.")
        if LOCK_FILE.exists() and not args.force_test:
            sys.exit("발표용 세트가 잠겨 있어요 (samples/test_lock.json). 다시 만들면 잠금이 깨져요.")
        sets += read_csv("sets_test.csv")
    elif TEST_SETS.exists() and not any((ROOT / "samples/test").glob("*/doc_a.*")):
        print("  주의: 발표용 서류가 아직 없어요. 만들려면 --test")
    check(parties, items, sets)
    print(f"거래처 {len(parties)}, 품목 {len(items)}, 세트 {len(sets)}")

    work = Path(tempfile.mkdtemp(prefix="samples_"))
    wb = load_workbook(TEMPLATE)
    layout = desc_layout(wb)
    extend_calc(wb["계산"], len(sets))
    fill_sheet(wb["거래처"], parties); fill_sheet(wb["품목"], [printed_item(i) for i in items]); fill_sheet(wb["세트"], sets)
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
    for split, (n_err, n_ok) in write_eval(first["계산"], sets, items).items():
        where = "eval/test/" if split == "test" else "eval/"
        print(f"정답지({split}): 심은 오류 {n_err}건, 정상 세트 {n_ok}개 → {where}answers.csv, fields.csv, sets.csv")

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
            fit_descriptions(v[sheet], layout[sheet])                   # 긴 품명이 잘리지 않게 행 높이
            p = work / "single" / f"{s['set_id']}__{slot}.xlsx"; p.parent.mkdir(exist_ok=True)
            v.save(p); singles.append(p); plan.append((s, slot, p.stem))
    soffice(cmd, "pdf", work / "pdf", singles)
    over = pdf_pages(work / "pdf")
    if over:
        sys.exit("서류가 한 장을 넘었어요 (품명이 길거나 줄이 많음): " + ", ".join(over))

    # 4) 제자리에 저장. png면 pdftoppm으로 바꾼다
    pdftoppm = shutil.which("pdftoppm")
    for s, slot, stem in plan:
        dest = ROOT / "samples" / s["split"] / s["set_id"]; dest.mkdir(parents=True, exist_ok=True)
        for old in dest.glob(f"{slot}.*"):              # pdf↔png가 바뀌어도 예전 파일이 남지 않게
            old.unlink()
        pdf = work / "pdf" / f"{stem}.pdf"
        if s["format"] == "png":
            if not pdftoppm:
                sys.exit("png 변환에 pdftoppm이 필요해요. 맥: brew install poppler")
            subprocess.run([pdftoppm, "-r", "150", "-png", "-singlefile", str(pdf), str(dest / slot)], check=True)
        else:
            shutil.copy(pdf, dest / f"{slot}.pdf")
    shutil.rmtree(work, ignore_errors=True)
    print(f"서류 {len(plan)}장 → " + ", ".join(f"samples/{x}" for x in sorted({s['split'] for s, _, _ in plan})))
    if any(s["split"] == "test" for s in targets):
        print("발표용을 만들었어요. 확인한 뒤 check_samples.py --lock-test 로 잠그세요.")


if __name__ == "__main__":
    main()
