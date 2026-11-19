"""데이터셋 생성기. 카탈로그(samples/gen/)와 규칙으로 키트 입력(samples/data/*.csv)을 만든다.

사용법 (저장소 맨 위에서)
  .venv/bin/python samples/generate_dataset.py                개발용 세트를 새로 만든다. 발표용은 없을 때 한 번만 만든다
  .venv/bin/python samples/generate_dataset.py --dev 75 --test 50 --seed 6
  .venv/bin/python samples/generate_dataset.py --force-test   발표용도 다시 만든다 (잠그기 전에만 된다)
이어서 서류와 정답지를 만들고 확인한다
  .venv/bin/python samples/build_samples.py [--test] && .venv/bin/python samples/check_samples.py --docs

입력  samples/gen/parties.csv, samples/gen/items.csv  (카탈로그. 사람이 고쳐 쓴다)
      refs/hs/관세청_HS부호_20260101.xlsx            (정답 HS와 단위 검증. 없으면 검증만 건너뛴다)
출력  samples/data/parties.csv, items.csv, sets.csv  개발용. git에 올린다
      samples/data/sets_test.csv                     발표용. git에 올리지 않는다
개발용과 발표용은 난수와 번호대를 따로 써서, 개발용을 바꿔도 발표용은 그대로다.
적용하는 규칙(G)과 심는 오류(E)는 samples/RULES.md 에 있다. 같은 시드면 같은 결과가 나온다.
"""
import argparse, csv, datetime as dt, math, random, re, shutil, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN, DATA = ROOT / "samples/gen", ROOT / "samples/data"
HS_TABLE = ROOT / "refs/hs/관세청_HS부호_20260101.xlsx"
TEST_FILE, LOCK_FILE = DATA / "sets_test.csv", ROOT / "samples/test_lock.json"

# ── 생성 규칙 (RULES.md 의 G 번호) ───────────────────────────────────────────
DISCHARGE = "BUSAN, KOREA"                                              # G1 부산항 수입
INVOICE_FROM, INVOICE_TO = dt.date(2026, 9, 1), dt.date(2026, 11, 12)    # G6 송장일 범위
SAIL_AFTER = (2, 9)                                                     # G6 선적일 = 송장일 + 2~9일
INCOTERMS = [("FOB", 55), ("CIF", 20), ("CFR", 15), ("EXW", 10)]        # G4 비율(%)
PAYMENT = [("T/T IN ADVANCE", 30), ("T/T 30 DAYS AFTER B/L DATE", 35), ("L/C AT SIGHT", 20), ("D/P AT SIGHT", 15)]
VESSELS = ["SAMPLE STAR", "EXAMPLE OCEAN", "SAMPLE PIONEER", "EXAMPLE BRIDGE",
           "SAMPLE HARMONY", "EXAMPLE VOYAGER", "SAMPLE HORIZON", "EXAMPLE PEARL"]
VOYAGE_DIR = {"CHINA": "E", "VIETNAM": "N"}                             # G5 항차 방향 글자
LINE_COUNT = [(1, 50), (2, 30), (3, 20)]                                # 세트당 품목 줄 수 비율(%)
PARTIAL_CARTON = 0.2                                                    # G7 끝 박스가 덜 찬 세트 비율
UNIT_HS = {"PCS": {"U"}, "PRS": {"2U"}, "M2": {"M2"}, "KGS": {"KG"}}       # G3 송장 단위 ↔ HS 수량단위
HS_PRINT = {"6": lambda h: f"{h[:4]}.{h[4:6]}",                          # G8 송장에 찍는 HS 모양
            "10": lambda h: f"{h[:4]}.{h[4:6]}-{h[6:]}",
            "none": lambda h: ""}
SEQ_START = {"dev": (100, 300), "test": (1100, 1300)}                   # G9 번호대: 개발용 100~, 발표용 1100~

# ── 심는 오류 (RULES.md 의 E 번호). 포장명세서(PL)의 한 칸만 바꾼다 ───────────────
FIELDS = ["total_qty", "total_gross_kg", "invoice_no"]
MECHANISMS = {"total_qty": ["digit_swap", "zero_slip", "carton_slip"],
              "total_gross_kg": ["decimal_shift", "digit_swap", "net_as_gross", "lb_as_kg"],
              "invoice_no": ["char_swap", "digit_typo"]}

SET_COLUMNS = ["set_id", "split", "style", "doc_a", "format", "exporter_id", "consignee_id", "invoice_no",
               "invoice_date", "po_no", "port_loading", "port_discharge", "vessel_voyage", "sailing_date",
               "incoterms", "payment_term", "origin", "item1_code", "item1_qty", "item2_code", "item2_qty",
               "item3_code", "item3_qty", "PL_invoice_no", "PL_qty1", "PL_qty2", "PL_qty3", "PL_gross1",
               "PL_gross2", "PL_gross3", "CI_total_amount_ovr", "PL_total_gross_ovr", "error_note"]
NUM = ("unit_price_usd", "net_kg_per_unit", "units_per_ctn", "ctn_tare_kg", "cbm_per_ctn", "qty_min", "qty_max", "qty_step")


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if (r.get(next(iter(r))) or "").strip()]


def write(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def weighted(rng, pairs):
    return rng.choices([v for v, _ in pairs], weights=[w for _, w in pairs])[0]


def fmt_num(v):
    """숫자를 반올림하지 않고 글자로 (1.0 → 1, 0.042 → 0.042, 1708.8 → 1708.8)."""
    v = float(v)
    return str(int(v)) if v == int(v) else f"{v:.6f}".rstrip("0").rstrip(".")


def line_calc(item, qty):
    """양식(계산 시트)과 같은 식: 박스 = 올림(수량/박스당), 순중량 = 수량×단위중량, 총중량 = 순중량+박스×박스무게."""
    ctns = math.ceil(qty / item["units_per_ctn"] - 1e-9)
    net = round(qty * item["net_kg_per_unit"] + 1e-9, 2)
    return ctns, net, round(net + ctns * item["ctn_tare_kg"] + 1e-9, 2)


# ── HS 검증 (G2·G3) ──────────────────────────────────────────────────────────
def check_hs(items):
    if not HS_TABLE.exists():
        print(f"  주의: {HS_TABLE.relative_to(ROOT)} 가 없어 정답 HS 검증을 건너뜀")
        return []
    from openpyxl import load_workbook
    table = defaultdict(list)
    for r in load_workbook(HS_TABLE, read_only=True).worksheets[0].iter_rows(min_row=2, values_only=True):
        if r[0]:
            table[str(r[0])].append(r)
    problems = []
    for it in items:
        rows = [r for r in table.get(it["hs10_answer"], [])
                if r[1].date() <= INVOICE_FROM and INVOICE_TO <= r[2].date()]
        if not rows:
            problems.append(f"{it['item_code']}: 정답 HS {it['hs10_answer']}가 HS 표에 없거나 송장 기간에 유효하지 않음")
            continue
        if rows[0][9] and rows[0][9] not in UNIT_HS.get(it["unit"], set()):
            problems.append(f"{it['item_code']}: 송장 단위 {it['unit']}가 HS 수량단위 {rows[0][9]}와 맞지 않음")
    return problems


# ── 오류 심기 (E) ────────────────────────────────────────────────────────────
def swap_digits(text, rng, lead_zero_ok=False):
    spots = [i for i in range(len(text) - 1)
             if text[i].isdigit() and text[i + 1].isdigit() and text[i] != text[i + 1]
             and (lead_zero_ok or not (i == 0 and text[1] == "0"))]
    if not spots:
        return None
    i = rng.choice(spots)
    return text[:i] + text[i + 1] + text[i] + text[i + 2:]


def qty_error(kind, rng, q, upc):
    if kind == "digit_swap":
        s = swap_digits(str(q), rng)
        v = int(s) if s else None
    elif kind == "zero_slip":
        v = q // 10 if q % 10 == 0 and rng.random() < 0.5 else q * 10
    else:  # carton_slip: 한 박스만큼 더하거나 뺌
        v = q + int(upc) * rng.choice((-1, 1)) if upc >= 1 else None
    return v if v and v > 0 and v != q else None


def gross_error(kind, rng, net, gross):
    if kind == "decimal_shift":
        v = round(gross / 10, 2) if rng.random() < 0.5 else round(gross * 10, 2)
    elif kind == "digit_swap":
        ip, dp = f"{gross:.2f}".split(".")
        s = swap_digits(ip, rng)
        v = float(f"{s}.{dp}") if s else None
    elif kind == "net_as_gross":
        v = net
    else:  # lb_as_kg: 파운드 값을 kg 칸에 적음
        v = round(gross * 2.20462, 2)
    return v if v is not None and abs(v - gross) >= 0.1 else None   # 허용 오차(0.1kg)보다 크게


def invoice_error(kind, rng, inv, taken):
    """끝 번호 세 자리 안에서만 바꾼다(번호대를 넘지 않게). 데이터에 이미 있는 번호가 되면 다시 뽑는다."""
    m = re.search(r"\d+$", inv)
    if not m:
        return None
    start = max(m.start(), m.end() - 3)
    head, tail = inv[:start], inv[start:]
    for _ in range(20):
        if kind == "char_swap":
            s = swap_digits(tail, rng, lead_zero_ok=True)
            v = head + s if s else None
        else:  # digit_typo
            i = rng.randrange(len(tail))
            v = head + tail[:i] + rng.choice([d for d in "0123456789" if d != tail[i]]) + tail[i + 1:]
        if v and v != inv and v not in taken:
            return v
    return None


def plant(rng, s, lines, field, kind_cycle, taken):
    """field 하나에 오류를 심는다. 고른 방식이 안 맞으면 같은 칸의 다른 방식으로."""
    kinds = MECHANISMS[field]
    start = kind_cycle[field] % len(kinds)
    for kind in kinds[start:] + kinds[:start]:
        if field == "invoice_no":
            v = invoice_error(kind, rng, s["invoice_no"], taken)
            if v:
                taken.add(v)
                s["PL_invoice_no"] = v
                s["error_note"] = f"[invoice_no:{kind}] PL 송장 번호 {s['invoice_no']}→{v}"
                break
        else:
            n = rng.randrange(len(lines))
            item, qty = lines[n]
            ctns, net, gross = line_calc(item, qty)
            if field == "total_qty":
                v = qty_error(kind, rng, qty, item["units_per_ctn"])
                if v:
                    s[f"PL_qty{n + 1}"] = str(v)
                    s["error_note"] = f"[total_qty:{kind}] PL {n + 1}행 수량 {qty}→{v}"
                    break
            else:
                v = gross_error(kind, rng, net, gross)
                if v is not None:
                    s[f"PL_gross{n + 1}"] = fmt_num(v)
                    s["error_note"] = f"[total_gross_kg:{kind}] PL {n + 1}행 총중량 {fmt_num(gross)}→{fmt_num(v)}"
                    break
    else:
        return None
    kind_cycle[field] += 1
    return kind


# ── 세트 만들기 (G) ──────────────────────────────────────────────────────────
def pick_qty(rng, item):
    step = item["qty_step"]
    q = rng.randint(math.ceil(item["qty_min"] / step), int(item["qty_max"] // step)) * step
    upc = item["units_per_ctn"]
    if item["unit"] in ("PCS", "PRS") and upc > 1 and q > upc and rng.random() < PARTIAL_CARTON:
        q -= rng.randint(1, int(upc) - 1)                 # G7 마지막 박스가 덜 참
    return int(round(q))


def balanced(rng, values, n):
    out = (values * (n // len(values) + 1))[:n]
    rng.shuffle(out)
    return out


def make_split(rng, split, prefix, slots, parties, items):
    exporters = [p for p in parties if p["role"] == "exporter"]
    by_exp = defaultdict(list)
    for it in items:
        by_exp[it["exporter_id"]].append(it)
    n = len(slots)
    styles, docs_a = balanced(rng, ["1", "2"], n), balanced(rng, ["CI", "PL"], n)
    formats = balanced(rng, ["pdf", "pdf", "pdf", "png", "png"], n)    # pdf 60%, png 40%
    exps = balanced(rng, exporters, n)
    sets = []
    for k in range(n):
        ex = exps[k]
        first = rng.choice(by_exp[ex["party_id"]])
        group = [it for it in by_exp[ex["party_id"]] if it["mix_group"] == first["mix_group"] and it is not first]
        want = min(weighted(rng, LINE_COUNT), 1 + len(group))
        chosen = [first] + rng.sample(group, want - 1)
        buyer = first["buyer_group"]
        con = {"food": "KR04", "home": rng.choice(["KR05", "KR05", "KR01"])}.get(buyer, rng.choice(["KR01", "KR02", "KR03"]))
        inv_date = INVOICE_FROM + dt.timedelta(days=rng.randint(0, (INVOICE_TO - INVOICE_FROM).days))
        port = ex["port"]
        term = weighted(rng, INCOTERMS)
        place = {"FOB": port.split(",")[0], "EXW": ex["city"]}.get(term, "BUSAN")      # G4 지정 장소
        s = {c: "" for c in SET_COLUMNS}
        s.update(set_id=f"{prefix}{k + 1:03d}", split=split, style=styles[k], doc_a=docs_a[k], format=formats[k],
                 exporter_id=ex["party_id"], consignee_id=con, invoice_date=inv_date.isoformat(),
                 port_loading=port, port_discharge=DISCHARGE,
                 vessel_voyage=f"{rng.choice(VESSELS)} {rng.randint(1, 999):03d}{VOYAGE_DIR[ex['country']]}",
                 sailing_date=(inv_date + dt.timedelta(days=rng.randint(*SAIL_AFTER))).isoformat(),
                 incoterms=f"{term} {place}", payment_term=weighted(rng, PAYMENT), origin=ex["country"])
        lines = []
        for i, it in enumerate(chosen, 1):
            q = pick_qty(rng, it)
            s[f"item{i}_code"], s[f"item{i}_qty"] = it["item_code"], str(q)
            lines.append((it, q))
        s["_lines"], s["_error"] = lines, slots[k]
        sets.append(s)
    number_documents(rng, sets, {p["party_id"]: p for p in parties}, split)
    return sets


def number_documents(rng, sets, party, split):
    """G9 송장·주문 번호: 거래처마다 고유 형식, 날짜 순서대로 커짐. 개발용과 발표용은 번호대가 달라 겹치지 않는다."""
    lo, hi = SEQ_START[split]
    for key, col in (("exporter_id", "invoice_no"), ("consignee_id", "po_no")):
        seq = {}
        for s in sorted(sets, key=lambda s: (s[key], s["invoice_date"], s["set_id"])):
            pid = s[key]
            seq[pid] = seq.get(pid, rng.randint(lo, hi)) + rng.randint(1, 6)
            d = dt.date.fromisoformat(s["invoice_date"])
            s[col] = party[pid]["doc_no_format"].format(yy=f"{d.year % 100:02d}", yyyy=d.year, n=seq[pid])


def build_split(seed, split, prefix, n, error_rate, parties, items):
    """한 분할(개발용·발표용)을 만든다. 분할마다 난수를 따로 써서 서로 영향을 주지 않는다."""
    rng = random.Random(f"{seed}:{split}")
    n_err = round(n * error_rate)
    slots = [FIELDS[i % 3] for i in range(n_err)] + [None] * (n - n_err)
    rng.shuffle(slots)
    sets = make_split(rng, split, prefix, slots, parties, items)
    taken = {s["invoice_no"] for s in sets}
    kind_cycle, planted = Counter(), Counter()
    for s in sets:
        if s["_error"]:
            kind = plant(rng, s, s["_lines"], s["_error"], kind_cycle, taken)
            if kind is None:
                sys.exit(f"{s['set_id']}: {s['_error']} 오류를 심지 못했어요")
            planted[(s["_error"], kind)] += 1
    return sets, planted


def clean_old(split, sets):
    """그 분할의 새 세트에 없는 예전 서류 폴더를 지운다 (doc_a·doc_b 파일만 든 폴더만)."""
    keep, removed, d = {s["set_id"] for s in sets}, [], ROOT / "samples" / split
    for p in sorted(d.iterdir()) if d.exists() else []:
        if p.is_dir() and re.fullmatch(r"[A-Z]+\d+", p.name) and p.name not in keep \
                and all(f.name.split(".")[0] in ("doc_a", "doc_b") for f in p.iterdir()):
            shutil.rmtree(p)
            removed.append(f"{split}/{p.name}")
    return removed


def summary(split, sets, planted):
    n_err = sum(planted.values())
    print(f"  {split}: 세트 {len(sets)} · 정상 {len(sets) - n_err}, 심은 오류 {n_err}  "
          + ", ".join(f"{f}/{k} {v}" for (f, k), v in sorted(planted.items())))
    print(f"    품목 줄 수 {dict(sorted(Counter(len(s['_lines']) for s in sets).items()))} · "
          f"인코텀즈 {dict(Counter(s['incoterms'].split()[0] for s in sets))}")


def main():
    ap = argparse.ArgumentParser(description="규칙 기반 데이터셋 생성기")
    ap.add_argument("--dev", type=int, default=75, help="개발용 세트 수")
    ap.add_argument("--test", type=int, default=50, help="발표용 세트 수 (발표용을 새로 만들 때만 쓰임)")
    ap.add_argument("--error-rate", type=float, default=0.6, help="오류를 심는 세트 비율")
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--force-test", action="store_true", help="발표용 세트도 다시 만든다 (잠그기 전에만)")
    args = ap.parse_args()

    parties, items = read(GEN / "parties.csv"), read(GEN / "items.csv")
    for it in items:
        for k in NUM:
            it[k] = float(it[k])
    problems = check_hs(items)
    if problems:
        sys.exit("HS 검증 실패:\n  " + "\n  ".join(problems))

    write(DATA / "parties.csv", ["party_id", "role", "name", "address", "country", "tel"], parties)
    kit_items = [{**it, **{k: fmt_num(it[k]) for k in NUM}, "hs_on_invoice": HS_PRINT[it["hs_print"]](it["hs10_answer"])}
                 for it in items]
    write(DATA / "items.csv", ["item_code", "description", "unit", "unit_price_usd", "hs10_answer", "net_kg_per_unit",
                               "units_per_ctn", "ctn_tare_kg", "cbm_per_ctn", "hs_on_invoice"], kit_items)
    print(f"거래처 {len(parties)} · 품목 {len(items)} · 시드 {args.seed}")

    dev, planted = build_split(args.seed, "dev", "D", args.dev, args.error_rate, parties, items)
    write(DATA / "sets.csv", SET_COLUMNS, dev)
    removed = clean_old("dev", dev)
    summary("dev", dev, planted)

    if TEST_FILE.exists() and not args.force_test:
        print("  test: 그대로 둠 (samples/data/sets_test.csv). 다시 만들려면 --force-test")
    elif LOCK_FILE.exists():
        sys.exit("발표용 세트가 잠겨 있어요 (samples/test_lock.json). 정말 다시 만들려면 잠금 파일을 먼저 지우세요.")
    else:
        test, planted = build_split(args.seed, "test", "T", args.test, args.error_rate, parties, items)
        write(TEST_FILE, SET_COLUMNS, test)
        removed += clean_old("test", test)
        summary("test", test, planted)
        print("  → 발표용 서류는 build_samples.py --test 로 만든다")
    if removed:
        print(f"  예전 서류 폴더 정리: {', '.join(removed)}")
    print("→ 다음: .venv/bin/python samples/build_samples.py")


if __name__ == "__main__":
    main()
