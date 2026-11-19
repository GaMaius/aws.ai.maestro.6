"""데이터셋 생성기. 카탈로그(samples/gen/)와 규칙으로 키트 입력(samples/data/*.csv)을 만든다.

사용법 (저장소 맨 위에서)
  .venv/bin/python samples/generate_dataset.py                개발용 세트를 새로 만든다. 발표용은 없을 때 한 번만 만든다
  .venv/bin/python samples/generate_dataset.py --dev 75 --test 50 --seed 6
  .venv/bin/python samples/generate_dataset.py --force-test   발표용도 다시 만든다 (잠그기 전에만 된다)
이어서 서류와 정답지를 만들고 확인한다
  .venv/bin/python samples/build_samples.py [--test] && .venv/bin/python samples/check_samples.py --docs

입력  samples/gen/parties.csv, items.csv              카탈로그 (사람이 고쳐 쓴다)
      samples/gen/parties_test.csv, items_test.csv    발표용에만 쓰는 거래처·품목 (git에 올리지 않는다. 없으면 건너뛴다)
      refs/hs/관세청_HS부호_20260101.xlsx              정답 HS·헷갈리는 HS와 단위 검증 (없으면 검증만 건너뛴다)
출력  samples/data/parties.csv, items.csv, sets.csv                 개발용. git에 올린다
      samples/data/parties_test.csv, items_test.csv, sets_test.csv  발표용. git에 올리지 않는다
세트 하나 = 상업송장 + 포장명세서 + 선하증권(B/L) + 원산지증명서(약 80%).
개발용과 발표용은 난수와 번호대를 따로 써서, 개발용을 바꿔도 발표용은 그대로다.
지키는 규칙(G), 심는 오류(E), 헷갈리지만 정상인 차이(V)는 samples/RULES.md 에 있다. 같은 시드면 같은 결과가 나온다.
"""
import argparse, csv, datetime as dt, json, math, random, re, shutil, sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN, DATA = ROOT / "samples/gen", ROOT / "samples/data"
HS_TABLE = ROOT / "refs/hs/관세청_HS부호_20260101.xlsx"
TEST_FILE, LOCK_FILE = DATA / "sets_test.csv", ROOT / "samples/test_lock.json"

# ── 생성 규칙 (RULES.md 의 G 번호) ───────────────────────────────────────────
DISCHARGE = "BUSAN, KOREA"                                              # G1 부산항 수입
INVOICE_FROM, INVOICE_TO = dt.date(2026, 9, 1), dt.date(2026, 11, 5)     # G6 송장일 범위
DATA_UNTIL = dt.date(2026, 11, 19)                                      # G6 서류 날짜는 해커톤(11/20) 전날을 넘지 않는다
SAIL_AFTER = (2, 9)                                                     # G6 선적일 = 송장일 + 2~9일
INCOTERMS = [("FOB", 55), ("CIF", 20), ("CFR", 15), ("EXW", 10)]        # G4 비율(%)
PAYMENT = [("T/T IN ADVANCE", 30), ("T/T 30 DAYS AFTER B/L DATE", 35), ("L/C AT SIGHT", 20), ("D/P AT SIGHT", 15)]
VESSELS = ["SAMPLE STAR", "EXAMPLE OCEAN", "SAMPLE PIONEER", "EXAMPLE BRIDGE",
           "SAMPLE HARMONY", "EXAMPLE VOYAGER", "SAMPLE HORIZON", "EXAMPLE PEARL"]
VOYAGE_DIR = {"CHINA": "E", "VIETNAM": "N"}                             # G5 항차 방향 글자
LINE_COUNT = [(1, 35), (2, 40), (3, 25)]                                # G11 세트당 품목 줄 수 비율(%)
PARTIAL_CARTON = 0.2                                                    # G7 끝 박스가 덜 찬 세트 비율
UNIT_HS = {"PCS": {"U"}, "PRS": {"2U"}, "M2": {"M2"}, "KGS": {"KG"}, "SET": {"SET", "U"}}   # G3 송장 단위 ↔ HS 수량단위
HS_PRINT = {"6": lambda h: f"{h[:4]}.{h[4:6]}",                          # G8 송장에 찍는 HS 모양
            "10": lambda h: f"{h[:4]}.{h[4:6]}-{h[6:]}",
            "none": lambda h: ""}
SEQ_START = {"dev": (100, 300), "test": (1100, 1300)}                   # G9 번호대: 개발용 100~, 발표용 1100~
FORMATS = {"format": ["pdf"] * 9 + ["png"] * 5 + ["scan"] * 6,          # G13 상업송장·포장명세서: pdf 45, png 25, 스캔 30
           "format_bl": ["pdf"] * 3 + ["scan"] * 2,                     #     B/L: pdf 60, 스캔 40
           "format_co": ["pdf"] * 9 + ["scan"] * 11}                    #     원산지증명서: pdf 45, 스캔 55
CO_RATE = 0.8                                                           # G15 원산지증명서가 있는 세트 비율
CO_FORMS = {"CHINA": [("KCFTA", 1)], "VIETNAM": [("AK", 6), ("VK", 4)]}  # G15 수출국별 협정 서식
OC_CODES = {"KCFTA": {"WO": ["WO"], "MANUF": ["PSR", "PSR", "PSR", "WP"]},   # G15 원산지 기준 (품목의 origin_basis 로 고른다)
            "AK": {"WO": ["WO"], "MANUF": ["CTH", "RVC 40%"]},                 # 한-중: WO·WP·PSR·OP, AK: WO·CTH·RVC 40% 등
            "VK": {"WO": ["WO"], "MANUF": ["CTC", "RVC 40%"]}}                 # VK: WO·CTC·RVC 40% 등 (PSR 없음)
WRONG_CODE = {"KCFTA": "CTH", "AK": "PSR", "VK": "PSR"}                 # E 그 협정 서식에 없는 기준 (다른 협정의 코드)
CO_WINDOW = {"KCFTA": 7, "AK": 2, "VK": 2}  # G15 선적 뒤 발급할 수 있는 근무일 (한-중 3.15: 7근무일, AK·VK: 선적일 포함 3근무일)
CARRIERS = [("SAMPLE LINE CO., LTD.", "SMLN", ("SMLU", "SMCU"), "SL"),  # G14 운송사: 이름, B/L 앞글자, 컨테이너 소유자 코드, 봉인 앞글자
            ("EXAMPLE SHIPPING CO., LTD.", "EXSH", ("EXSU", "EXMU"), "EX"),
            ("SAMPLE OCEAN LINES LTD.", "SOCL", ("SOLU", "SOCU"), "SO")]
LC_BANKS = ["SAMPLE BANK OF KOREA, BUSAN BRANCH", "EXAMPLE COMMERCIAL BANK, BUSAN BRANCH"]
PORT_CODE = {"SHANGHAI": "SHA", "SHENZHEN": "SZX", "NINGBO": "NGB", "QINGDAO": "TAO", "GUANGZHOU": "CAN",
             "XIAMEN": "XMN", "TIANJIN": "TSN", "HO CHI MINH CITY": "SGN", "HAIPHONG": "HPH", "DA NANG": "DAD"}
CONTAINERS = {"20GP": (27, 21500), "40HC": (66, 26000), "40RH": (57, 26000)}   # G14 컨테이너: 실을 수 있는 CBM, kg
LCL_CBM = 10                                                            # G14 이보다 작으면 LCL(혼재) 화물

# ── 심는 오류 (RULES.md 의 E 번호) ───────────────────────────────────────────
ERROR_RATE_SECOND = 0.2                     # 오류 세트 중 오류를 하나 더 심는 비율
CATEGORIES = [("invoice_no", 20), ("total_qty", 23), ("total_gross_kg", 23),   # P0: 상업송장 ↔ 포장명세서
              ("sum", 6), ("hs", 9), ("bl", 10), ("co", 9)]                    # P1: 합계, 송장 HS, B/L, 원산지증명서
P0_FIELDS = ("invoice_no", "total_qty", "total_gross_kg")
KINDS = {"invoice_no": ["char_swap", "digit_typo"],
         "total_qty": ["digit_swap", "zero_slip", "carton_slip"],
         "total_gross_kg": ["decimal_shift", "digit_swap", "net_as_gross", "lb_as_kg"]}
BL_OPTIONS = [("total_gross_kg", "net_as_gross"), ("total_packages", "carton_slip"), ("container_no", "check_digit"),
              ("freight_term", "incoterms_conflict"), ("total_gross_kg", "digit_swap"),
              ("total_packages", "digit_swap"), ("container_no", "char_swap")]
CO_OPTIONS = [("hs_code", "trap_code"), ("invoice_no", "char_swap"), ("origin_criterion", "wo_on_manufactured"),
              ("issue_date", "late_without_retro"), ("hs_code", "digit_typo"), ("departure_date", "date_mismatch"),
              ("origin_criterion", "wrong_code_set"), ("invoice_no", "digit_typo"), ("origin_criterion", "missing")]
# 헷갈리지만 정상인 차이 (RULES.md 의 V 번호). 정상 세트에만 넣고, 그 세트에 쓸 수 있는 것 중에서 비율대로 고른다
VARIANT_RATE = 0.45
VARIANTS = [("co_desc_typo", 35),       # V3 원산지증명서 품명의 사소한 오타 (FTA 사무처리 고시 제13조①, ISBP A23)
            ("gross_rounding", 25),     # V1 총중량 반올림 차이 0.05kg 이하 (팀 허용 오차 0.1kg 안)
            ("co_retroactive", 30),     # V4 늦게 발급했지만 ISSUED RETROACTIVELY 표시가 있는 원산지증명서 (1년 안이면 유효)
            ("invoice_no_format", 10)]  # V2 송장 번호 구분 기호만 다름 (근거 약함: ISBP A23 유추라 적게)

SET_COLUMNS = ["set_id", "split", "style", "doc_a", "format", "exporter_id", "consignee_id", "invoice_no",
               "invoice_date", "po_no", "port_loading", "port_discharge", "vessel_voyage", "sailing_date",
               "incoterms", "payment_term", "origin", "item1_code", "item1_qty", "item2_code", "item2_qty",
               "item3_code", "item3_qty", "PL_invoice_no", "PL_qty1", "PL_qty2", "PL_qty3", "PL_gross1",
               "PL_gross2", "PL_gross3", "CI_total_amount_ovr", "PL_total_gross_ovr", "error_note",
               "CI_invoice_no", "CI_qty1", "CI_qty2", "CI_qty3", "CI_total_gross_ovr", "CI_hs1", "CI_hs2", "CI_hs3",
               # 여기부터는 양식(templates.xlsx)에 없는 칸: B/L·원산지증명서와 정답
               "format_bl", "format_co", "carrier", "bl_no", "bl_consignee", "bl_notify", "bl_service",
               "bl_containers", "freight_term", "bl_originals", "bl_issue_date", "bl_show_hs",
               "co_form", "co_no", "co_issue_date", "co_retro", "co_criteria", "errors", "variants"]
ITEM_COLUMNS = ["item_code", "description", "unit", "unit_price_usd", "hs10_answer", "net_kg_per_unit",
                "units_per_ctn", "ctn_tare_kg", "cbm_per_ctn", "hs_on_invoice", "hs_print", "trap_hs", "hs6_2012",
                "bl_desc", "bl_note", "origin_basis"]
PARTY_COLUMNS = ["party_id", "role", "name", "address", "country", "tel", "city", "port"]
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


def rnd(x, n=2):
    """양식(LibreOffice)의 ROUND 와 같게: 0.5는 올린다 (파이썬 round 는 짝수 쪽으로 보낸다)."""
    return float(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-n), rounding=ROUND_HALF_UP))


def fmt_hs(code, digits):
    return HS_PRINT[digits](code)


def line_calc(item, qty):
    """양식(계산 시트)과 같은 식: 박스 = 올림(수량/박스당), 순중량 = 수량×단위중량, 총중량 = 순중량+박스×박스무게."""
    ctns = math.ceil(qty / item["units_per_ctn"] - 1e-9)
    net = rnd(qty * item["net_kg_per_unit"])
    return ctns, net, rnd(net + ctns * item["ctn_tare_kg"]), rnd(ctns * item["cbm_per_ctn"], 3)


def totals(lines):
    calc = [line_calc(it, q) for it, q in lines]
    return {"qty": sum(q for _, q in lines), "ctns": sum(c[0] for c in calc),
            "net": rnd(sum(c[1] for c in calc)), "gross": rnd(sum(c[2] for c in calc)),
            "cbm": rnd(sum(c[3] for c in calc), 3), "line_gross": [c[2] for c in calc],
            "amount": rnd(sum(rnd(q * it["unit_price_usd"]) for it, q in lines))}


# ── ISO 6346 컨테이너 번호 (G14) ──────────────────────────────────────────────
ISO_LETTER, _v = {}, 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _v += _v % 11 == 0                       # 11의 배수(11, 22, 33)는 건너뛴다
    ISO_LETTER[_ch], _v = _v, _v + 1


def iso_total(first10):
    return sum((ISO_LETTER[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(first10))


def check_digit(first10):
    """소유자 코드 4글자 + 일련번호 6자리의 체크 디지트. 글자 값 × 2^자리, 합을 11로 나눈 나머지의 끝자리."""
    return iso_total(first10) % 11 % 10


assert check_digit("CSQU305438") == 3, "ISO 6346 체크 디지트 계산이 틀림"   # BIC 공개 예시 CSQU3054383


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
        for key in ("hs10_answer", "trap_hs"):
            code = it.get(key, "")
            if key == "trap_hs" and not code:
                continue
            rows = [r for r in table.get(code, []) if r[1].date() <= INVOICE_FROM and INVOICE_TO <= r[2].date()]
            if not rows:
                problems.append(f"{it['item_code']}: {key} {code}가 HS 표에 없거나 송장 기간에 유효하지 않음")
            elif key == "hs10_answer" and rows[0][9] and rows[0][9] not in UNIT_HS.get(it["unit"], set()):
                problems.append(f"{it['item_code']}: 송장 단위 {it['unit']}가 HS 수량단위 {rows[0][9]}와 맞지 않음")
        if it.get("trap_hs") == it["hs10_answer"]:
            problems.append(f"{it['item_code']}: 헷갈리는 HS가 정답과 같음")
    return problems


# ── 오류 값 만들기 (E) ────────────────────────────────────────────────────────
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
        v = rnd(gross / 10) if rng.random() < 0.5 else rnd(gross * 10)
    elif kind == "digit_swap":
        ip, dp = f"{gross:.2f}".split(".")
        s = swap_digits(ip, rng)
        v = float(f"{s}.{dp}") if s else None
    elif kind == "net_as_gross":
        v = net
    else:  # lb_as_kg: 파운드 값을 kg 칸에 적음
        v = rnd(gross * 2.20462)
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


def invoice_format_variant(inv, rng):
    """V2 같은 번호를 다르게 적기: 구분 기호(-, /)를 빈칸으로 바꾸거나 빼거나, 글자와 숫자 사이에 - 를 넣는다."""
    seps = [i for i, ch in enumerate(inv) if ch in "-/"]
    if seps:
        i = rng.choice(seps)
        return inv[:i] + rng.choice([" ", ""] + (["-"] if inv[i] == "/" else [])) + inv[i + 1:]
    m = re.match(r"([A-Z]+)(\d+)$", inv)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def add_workdays(d, n):
    """d 다음 날부터 주말을 빼고 n 근무일 뒤 (공휴일은 무시)."""
    while n > 0:
        d += dt.timedelta(days=1)
        n -= d.weekday() < 5
    return d


def co_latest(s):
    """G15 원산지증명서를 소급 표시 없이 발급할 수 있는 마지막 날."""
    return add_workdays(dt.date.fromisoformat(s["sailing_date"]), CO_WINDOW[s["co_form"]])


def co_late(rng, s):
    """E·V4 발급 기한을 넘긴 날. 서류 날짜 한도(DATA_UNTIL)를 넘으면 None."""
    d = co_latest(s) + dt.timedelta(days=rng.randint(8, 30))
    return d if d <= DATA_UNTIL else None


def co_hs6(it, form):
    """원산지증명서에 찍는 HS 6자리. 한-중 FTA는 HS2012 코드가 따로 있으면 그것 (협정 HS 버전 차이)."""
    return it.get("hs6_2012") if form == "KCFTA" and it.get("hs6_2012") else it["hs10_answer"][:6]


def desc_typo(desc, rng):
    """V3 뜻이 바뀌지 않는 오타: 6글자 이상 낱말 하나에서 이웃 두 글자가 바뀌거나 한 글자가 빠진다 (COTTON → COTTNO, STAINLES)."""
    words = [(m.start(), m.group()) for m in re.finditer(r"[A-Z]{6,}", desc)]
    for _ in range(10):
        if not words:
            return None
        pos, w = rng.choice(words)
        i = rng.randrange(1, len(w) - 2)
        new = w[:i] + w[i + 1] + w[i] + w[i + 2:] if rng.random() < 0.5 else w[:i] + w[i + 1:]
        if new != w:
            return desc[:pos] + new + desc[pos + len(w):]
    return None


def rotate(cycle, key, options):
    """같은 종류가 몰리지 않게 돌아가며 고른다. 첫 후보가 안 맞으면 다음 후보로."""
    start = cycle[key] % len(options)
    cycle[key] += 1
    return options[start:] + options[:start]


def err(doc, field, kind, value, orig, line=None):
    num = lambda v: fmt_num(v) if isinstance(v, (int, float)) else str(v)
    return {"doc": doc, "field": field, "kind": kind, "value": num(value), "orig": num(orig), "line": line}


class Planter:
    """세트에 오류나 헷갈리는 차이를 심는다. 상업송장·포장명세서는 양식의 덮어쓰기 칸(CI_·PL_)에, B/L·원산지증명서는
    errors 칸(JSON)에 적고 build_samples.py 가 그 값으로 서류를 그린다."""

    def __init__(self, rng, taken):
        self.rng, self.taken, self.cycle = rng, taken, Counter()

    def side(self, field):
        return rotate(self.cycle, f"side:{field}", ["PL", "CI"])[0]      # 칸마다 상업송장·포장명세서 반반

    def invoice(self, s, doc):
        for kind in rotate(self.cycle, "invoice_no", KINDS["invoice_no"]):
            v = invoice_error(kind, self.rng, s["invoice_no"], self.taken)
            if v:
                self.taken.add(v)
                s[f"{doc}_invoice_no"] = v
                return err(doc, "invoice_no", kind, v, s["invoice_no"])

    def qty(self, s, doc, lines, t):
        for kind in rotate(self.cycle, "total_qty", KINDS["total_qty"]):
            n = self.rng.randrange(len(lines))
            item, q = lines[n]
            v = qty_error(kind, self.rng, q, item["units_per_ctn"])
            if v:
                s[f"{doc}_qty{n + 1}"] = str(v)
                return err(doc, "total_qty", kind, t["qty"] - q + v, t["qty"], n + 1)

    def gross(self, s, doc, lines, t):
        for kind in rotate(self.cycle, "total_gross_kg", KINDS["total_gross_kg"]):
            if doc == "PL":                                   # 포장명세서: 한 줄의 총중량을 바꾸고 합계가 따라 바뀜
                n = self.rng.randrange(len(lines))
                _, net, gross, _ = line_calc(*lines[n])
                v = gross_error(kind, self.rng, net, gross)
                if v is not None:
                    s[f"PL_gross{n + 1}"] = fmt_num(v)
                    total = rnd(sum(g for i, g in enumerate(t["line_gross"]) if i != n) + v)
                    return err("PL", "total_gross_kg", kind, total, t["gross"], n + 1)
            else:                                             # 상업송장: 총중량은 합계 한 칸뿐
                v = gross_error(kind, self.rng, t["net"], t["gross"])
                if v is not None:
                    s["CI_total_gross_ovr"] = fmt_num(v)
                    return err("CI", "total_gross_kg", kind, v, t["gross"])

    def sum(self, s, lines, t):
        """E 합계 오류: 줄 값은 맞는데 찍힌 합계가 틀림. 포장명세서 총중량이나 상업송장 총금액."""
        first = rotate(self.cycle, "sum_doc", ["PL", "CI"])[0]
        kinds = ["total_omits_line", "total_digit_swap"] if len(lines) > 1 else ["total_digit_swap"]
        for doc in (first, "CI" if first == "PL" else "PL"):    # 숫자를 바꿀 수 없으면 다른 서류로
            base = t["gross"] if doc == "PL" else t["amount"]
            for kind in rotate(self.cycle, "sum", kinds):
                n = None
                if kind == "total_omits_line":
                    n = self.rng.randrange(len(lines))
                    it, q = lines[n]
                    v = rnd(base - (t["line_gross"][n] if doc == "PL" else rnd(q * it["unit_price_usd"])))
                else:
                    ip, dp = f"{base:.2f}".split(".")
                    sw = swap_digits(ip, self.rng)
                    v = float(f"{sw}.{dp}") if sw else None
                if v is not None and abs(v - base) >= 0.1:
                    if doc == "PL":
                        s["PL_total_gross_ovr"] = fmt_num(v)
                        return err("PL", "total_gross_kg", kind, v, base, n + 1 if n is not None else None)
                    s["CI_total_amount_ovr"] = fmt_num(v)
                    return err("CI", "total_amount", kind, v, base, n + 1 if n is not None else None)

    def hs(self, s, lines):
        """E 송장 HS 오류: 스타일 2 상업송장의 HS 칸에 헷갈리는 HS를 찍는다. HS 6자리가 같으면 10자리로 찍는다.
        둘에 하나는 원산지증명서에도 같은 헷갈리는 HS를 찍고 B/L에는 HS를 빼서, 서류끼리는 맞는데 HS가 틀린 세트를 만든다
        (trap_all_docs). 서류 대조로는 못 잡고 품명으로 HS를 판단해야 잡힌다."""
        cand = [n for n, (it, _) in enumerate(lines) if it.get("trap_hs")]
        if s["style"] != "2" or not cand:
            return None
        every = [n for n in cand if s["co_form"] and lines[n][0]["trap_hs"][:6] != lines[n][0]["hs10_answer"][:6]
                 and co_hs6(lines[n][0], s["co_form"]) == lines[n][0]["hs10_answer"][:6]]
        all_docs = bool(every) and rotate(self.cycle, "hs_all", [True, False])[0]
        n = self.rng.choice(every if all_docs else cand)
        it = lines[n][0]
        digits = "10" if it["hs_print"] == "10" or it["trap_hs"][:6] == it["hs10_answer"][:6] else "6"
        v = fmt_hs(it["trap_hs"], digits)
        s[f"CI_hs{n + 1}"] = v
        kind = "trap_all_docs" if all_docs else "trap_code"
        out = [err("CI", f"items[{n}].hs_code", kind, v, fmt_hs(it["hs10_answer"], digits), n + 1)]
        if all_docs:
            s["bl_show_hs"] = ""
            out.append(err("CO", f"items[{n}].hs_code", kind, fmt_hs(it["trap_hs"], "6"), fmt_hs(it["hs10_answer"], "6"), n + 1))
        return out

    def bl(self, s, t):
        first = s["bl_containers"].split("|")[0].split("/")[0]
        for field, kind in rotate(self.cycle, "bl", BL_OPTIONS):
            v = None
            if field == "total_gross_kg":
                v, orig = gross_error(kind, self.rng, t["net"], t["gross"]), t["gross"]
            elif field == "total_packages":
                orig = t["ctns"]
                if kind == "carton_slip":
                    v = orig + self.rng.choice((-2, -1, 1, 2))
                else:
                    sw = swap_digits(str(orig), self.rng)
                    v = int(sw) if sw else None
                v = v if v and v > 0 and v != orig else None
            elif field == "container_no":
                orig = first
                if kind == "check_digit":
                    v = first[:10] + str((int(first[10]) + self.rng.randint(1, 9)) % 10)
                else:                                   # 일련번호 두 자리가 바뀜. 체크 디지트로 잡히는 경우만
                    sw = swap_digits(first[4:10], self.rng, lead_zero_ok=True)
                    v = first[:4] + sw + first[10] if sw else None
                    if v and check_digit(v[:10]) == int(v[10]):
                        v = None
            else:                                       # freight_term: 인코텀즈와 운임 조건이 어긋남
                orig = s["freight_term"]
                v = "FREIGHT COLLECT" if "PREPAID" in orig else "FREIGHT PREPAID"
            if v not in (None, ""):
                return err("BL", field, kind, v, orig)

    def co(self, s, lines):
        crit, form = s["co_criteria"].split("|"), s["co_form"]
        for field, kind in rotate(self.cycle, "co", CO_OPTIONS):
            if field == "invoice_no":
                v = invoice_error(kind, self.rng, s["invoice_no"], self.taken)
                if v:
                    self.taken.add(v)
                    return err("CO", "invoice_no", kind, v, s["invoice_no"])
                continue
            if field == "issue_date":                   # 발급 기한을 넘겼는데 소급 표시(ISSUED RETROACTIVELY)가 없음
                late = co_late(self.rng, s)
                if late:
                    orig = s["co_issue_date"]
                    s["co_issue_date"], s["co_retro"] = late.isoformat(), ""
                    return err("CO", "issue_date", kind, late.isoformat(), orig)
                continue
            if field == "departure_date":               # 원산지증명서의 출항일이 B/L 선적일과 다름
                v = dt.date.fromisoformat(s["sailing_date"]) + dt.timedelta(days=self.rng.choice((-3, -2, -1, 1, 2, 3)))
                return err("CO", "departure_date", kind, v.isoformat(), s["sailing_date"])
            if field == "hs_code":                      # 헷갈리는 HS는 협정 HS 버전 차이가 없는 품목에만
                cand = [n for n, (it, _) in enumerate(lines) if kind == "digit_typo"
                        or (it.get("trap_hs") and it["trap_hs"][:6] != it["hs10_answer"][:6]
                            and co_hs6(it, form) == it["hs10_answer"][:6])]
            elif kind == "wo_on_manufactured":
                cand = [n for n, (it, _) in enumerate(lines) if it["origin_basis"] != "WO"]
            else:
                cand = list(range(len(lines)))
            if not cand:
                continue
            n = self.rng.choice(cand)
            it = lines[n][0]
            if field == "hs_code":
                code6 = co_hs6(it, form)
                orig = fmt_hs(code6, "6")
                if kind == "trap_code":
                    v = fmt_hs(it["trap_hs"], "6")
                else:                                   # 소호(5~6번째 자리) 한 자리 오타
                    d = list(code6)
                    i = self.rng.choice((4, 5))
                    d[i] = self.rng.choice([x for x in "0123456789" if x != d[i]])
                    v = fmt_hs("".join(d), "6")
            else:
                orig = crit[n]
                v = {"wo_on_manufactured": "WO", "wrong_code_set": WRONG_CODE[form], "missing": ""}[kind]
                if v == orig:
                    continue
            return err("CO", f"items[{n}].{field}", kind, v, orig, n + 1)

    def p0(self, s, field, lines, t, doc=None):
        doc = doc or self.side(field)
        return {"invoice_no": lambda: self.invoice(s, doc), "total_qty": lambda: self.qty(s, doc, lines, t),
                "total_gross_kg": lambda: self.gross(s, doc, lines, t)}[field]()

    def variant(self, s, lines, t):
        rounding = [n for n, g in enumerate(t["line_gross"]) if rnd(g, 1) != g]
        usable = {"co_desc_typo": bool(s["co_form"]),
                  "gross_rounding": bool(rounding) or rnd(t["gross"], 1) != t["gross"],
                  "co_retroactive": bool(s["co_form"]) and co_latest(s) + dt.timedelta(days=8) <= DATA_UNTIL,
                  "invoice_no_format": bool(re.search(r"[-/]|^[A-Z]+\d+$", s["invoice_no"]))}
        options = [(k, w) for k, w in VARIANTS if usable[k]]
        if not options:
            return None
        kind = weighted(self.rng, options)
        if kind == "co_retroactive":                # V4 기한 뒤 발급 + 소급 표시 (1년 안이면 유효, 한-중 3.15(4)·VK 3.16(3))
            late = co_late(self.rng, s) or co_latest(s) + dt.timedelta(days=8)
            orig = s["co_issue_date"]
            s["co_issue_date"], s["co_retro"] = late.isoformat(), "1"
            return err("CO", "issue_date", kind, late.isoformat(), orig)
        if kind == "co_desc_typo":                  # V3 원산지증명서 한 줄 품명에 사소한 오타 (원산지증명서를 그릴 때 반영)
            n = self.rng.randrange(len(lines))
            v = desc_typo(lines[n][0]["description"], self.rng)
            if v:
                return err("CO", f"items[{n}].description", kind, v, lines[n][0]["description"], n + 1)
            return None
        if kind == "gross_rounding":                # V1 총중량을 소수 한 자리로 반올림해 적음 (차이 0.05kg 이하)
            if rounding:                            # 포장명세서 한 줄을 반올림하고 합계가 따라감
                n = self.rng.choice(rounding)
                v = rnd(t["line_gross"][n], 1)
                s[f"PL_gross{n + 1}"] = fmt_num(v)
                total = rnd(sum(g for i, g in enumerate(t["line_gross"]) if i != n) + v)
                return err("PL", "total_gross_kg", kind, total, t["gross"], n + 1)
            v = rnd(t["gross"], 1)                  # 상업송장 총중량(합계 한 칸)을 반올림
            s["CI_total_gross_ovr"] = fmt_num(v)
            return err("CI", "total_gross_kg", kind, v, t["gross"])
        v = invoice_format_variant(s["invoice_no"], self.rng)   # V2 같은 송장 번호를 구분 기호만 다르게
        if v and v != s["invoice_no"]:
            s["PL_invoice_no"] = v
            return err("PL", "invoice_no", kind, v, s["invoice_no"])
        return None


# ── 세트 만들기 (G) ──────────────────────────────────────────────────────────
def pick_qty(rng, item):
    step = item["qty_step"]
    q = rng.randint(math.ceil(item["qty_min"] / step), int(item["qty_max"] // step)) * step
    upc = item["units_per_ctn"]
    if item["unit"] in ("PCS", "PRS", "SET") and upc > 1 and q > upc and rng.random() < PARTIAL_CARTON:
        q -= rng.randint(1, int(upc) - 1)                 # G7 마지막 박스가 덜 참
    return int(round(q))


def balanced(rng, values, n):
    out = (values * (n // len(values) + 1))[:n]
    rng.shuffle(out)
    return out


def allocate(rng, n):
    """오류 세트 n개를 CATEGORIES 비율대로 나눈다 (큰 나머지 방식)."""
    total = sum(w for _, w in CATEGORIES)
    raw = [(c, n * w / total) for c, w in CATEGORIES]
    cnt = {c: int(x) for c, x in raw}
    for c, x in sorted(raw, key=lambda p: p[1] - int(p[1]), reverse=True)[: n - sum(cnt.values())]:
        cnt[c] += 1
    out = [c for c, k in cnt.items() for _ in range(k)]
    rng.shuffle(out)
    return out


def choose_lines(rng, items_of_exporter):
    """G11 줄 수를 먼저 뽑고, 그만큼 같이 실을 수 있는 품목 묶음(mix_group)에서 고른다."""
    groups = defaultdict(list)
    for it in items_of_exporter:
        groups[it["mix_group"]].append(it)
    want = weighted(rng, LINE_COUNT)
    fit = [g for g in groups.values() if len(g) >= want]
    group = rng.choice(fit) if fit else max(groups.values(), key=len)
    return rng.sample(group, min(want, len(group)))


def plan_containers(rng, t, frozen, carrier, taken):
    """G14 화물 부피·무게에 맞는 컨테이너. 박스는 고르게 나누고 무게·부피는 박스 비율로 (합은 총계와 같게)."""
    cbm, kg, pk = t["cbm"], t["gross"], t["ctns"]
    if frozen:
        kind = "40RH"
    elif kg > 400 * cbm or (cbm <= 25 and kg <= CONTAINERS["20GP"][1]):
        kind = "20GP"                                   # 무거운 화물(타일·커피 등)이나 작은 화물
    else:
        kind = "40HC"
    cap_cbm, cap_kg = CONTAINERS[kind]
    n = min(pk, max(1, math.ceil(cbm / cap_cbm), math.ceil(kg / cap_kg)))
    base, extra = divmod(pk, n)
    counts = [base + (i < extra) for i in range(n)]
    owners, seal_prefix = carrier[2], carrier[3]
    out, kg_left, cbm_left = [], kg, cbm
    for i, c in enumerate(counts):
        g, v = (rnd(kg_left), rnd(cbm_left, 3)) if i == n - 1 else (rnd(kg * c / pk), rnd(cbm * c / pk, 3))
        kg_left, cbm_left = kg_left - g, cbm_left - v
        while True:
            head = rng.choice(owners) + f"{rng.randint(0, 999999):06d}"
            no = head + str(check_digit(head))
            if no not in taken and iso_total(head) % 11 != 10:   # 나머지 10(체크 디지트 0과 겹침)은 피한다
                taken.add(no)
                break
        out.append(f"{no}/{seal_prefix}{rng.randint(1000000, 9999999)}/{kind}/{c}/{fmt_num(g)}/{fmt_num(v)}")
    return "|".join(out), ("CFS/CFS" if cbm < LCL_CBM and not frozen else "CY/CY")


def make_split(rng, split, prefix, slots, parties, items, test_consignees):
    exporters = [p for p in parties if p["role"] == "exporter"]
    party = {p["party_id"]: p for p in parties}
    by_exp = defaultdict(list)
    for it in items:
        by_exp[it["exporter_id"]].append(it)
    n = len(slots)
    styles, docs_a = balanced(rng, ["1", "2"], n), balanced(rng, ["CI", "PL"], n)
    fmts = {k: balanced(rng, v, n) for k, v in FORMATS.items()}
    exps = balanced(rng, exporters, n)
    has_co = balanced(rng, [True] * round(CO_RATE * 10) + [False] * (10 - round(CO_RATE * 10)), n)
    sets, containers_taken = [], set()
    for k in range(n):
        ex = exps[k]
        chosen = choose_lines(rng, by_exp[ex["party_id"]])
        buyer = chosen[0]["buyer_group"]
        con = {"food": "KR04", "home": rng.choice(["KR05", "KR05", "KR01"])}.get(buyer, rng.choice(["KR01", "KR02", "KR03"]))
        if test_consignees and rng.random() < 0.25:
            con = rng.choice(test_consignees)                  # 발표용 전용 수입자
        inv_date = INVOICE_FROM + dt.timedelta(days=rng.randint(0, (INVOICE_TO - INVOICE_FROM).days))
        sail = inv_date + dt.timedelta(days=rng.randint(*SAIL_AFTER))
        port = ex["port"]
        term = weighted(rng, INCOTERMS)
        place = {"FOB": port.split(",")[0], "EXW": ex["city"]}.get(term, "BUSAN")      # G4 지정 장소
        pay = weighted(rng, PAYMENT)
        s = {c: "" for c in SET_COLUMNS}
        s.update(set_id=f"{prefix}{k + 1:03d}", split=split, style=styles[k], doc_a=docs_a[k],
                 exporter_id=ex["party_id"], consignee_id=con, invoice_date=inv_date.isoformat(),
                 port_loading=port, port_discharge=DISCHARGE,
                 vessel_voyage=f"{rng.choice(VESSELS)} {rng.randint(1, 999):03d}{VOYAGE_DIR[ex['country']]}",
                 sailing_date=sail.isoformat(), incoterms=f"{term} {place}", payment_term=pay, origin=ex["country"],
                 **{f: fmts[f][k] for f in FORMATS})
        if slots[k] == "hs":
            s["style"] = "2"                                   # 송장 HS 칸은 스타일 2 상업송장에만 있다 (G8)
        lines = []
        for i, it in enumerate(chosen, 1):
            q = pick_qty(rng, it)
            s[f"item{i}_code"], s[f"item{i}_qty"] = it["item_code"], str(q)
            lines.append((it, q))
        t = totals(lines)
        # G14 B/L: 운송사, 컨테이너, 운임 조건, 수하인(신용장이면 은행 지시식), 원본 수
        carrier = rng.choice(CARRIERS)
        s["carrier"] = carrier[0]
        s["bl_containers"], s["bl_service"] = plan_containers(
            rng, t, any("frozen" in it["mix_group"] for it in chosen), carrier, containers_taken)
        s["freight_term"] = "FREIGHT PREPAID" if term in ("CIF", "CFR") else "FREIGHT COLLECT"
        if pay.startswith("L/C"):
            s["bl_consignee"], s["bl_notify"] = f"TO ORDER OF {rng.choice(LC_BANKS)}", "CONSIGNEE"
        elif pay.startswith("D/P"):
            s["bl_consignee"], s["bl_notify"] = "TO ORDER OF SHIPPER", "CONSIGNEE"
        else:
            s["bl_consignee"], s["bl_notify"] = "", "SAME AS CONSIGNEE"
        s["bl_originals"] = "0 (ZERO) - SURRENDERED" if pay.startswith("T/T") and rng.random() < 0.5 else "THREE (3)"
        s["bl_issue_date"] = (sail + dt.timedelta(days=rng.random() < 0.2)).isoformat()
        s["bl_show_hs"] = "1" if rng.random() < (0.7 if ex["country"] == "CHINA" else 0.3) else ""
        # G15 원산지증명서: 수출국에 맞는 협정 서식, 품목별 원산지 기준, 발급일은 송장일 이후 선적일 전후
        if has_co[k] or slots[k] in ("co", "hs"):            # 송장 HS 오류 세트는 원산지증명서에도 함정을 심을 수 있게
            form = weighted(rng, CO_FORMS[ex["country"]])
            s["co_form"] = form
            s["co_criteria"] = "|".join(rng.choice(OC_CODES[form][it["origin_basis"]]) for it, _ in lines)
            start, latest = sail - dt.timedelta(days=2), add_workdays(sail, CO_WINDOW[form])
            issue = start + dt.timedelta(days=rng.randint(0, (latest - start).days))
            s["co_issue_date"] = min(max(inv_date, issue), DATA_UNTIL).isoformat()
        else:
            s["format_co"] = ""
        s["_lines"], s["_t"], s["_slot"], s["_carrier"] = lines, t, slots[k], carrier
        sets.append(s)
    number_documents(rng, sets, party, split)
    return sets


def number_documents(rng, sets, party, split):
    """G9 송장·주문·B/L·원산지증명서 번호: 발급자마다 고유 형식, 날짜 순서대로 커짐. 개발용과 발표용은 번호대가 다르다."""
    lo, hi = SEQ_START[split]
    for key, col in (("exporter_id", "invoice_no"), ("consignee_id", "po_no")):
        seq = {}
        for s in sorted(sets, key=lambda s: (s[key], s["invoice_date"], s["set_id"])):
            pid = s[key]
            seq[pid] = seq.get(pid, rng.randint(lo, hi)) + rng.randint(1, 6)
            d = dt.date.fromisoformat(s["invoice_date"])
            s[col] = party[pid]["doc_no_format"].format(yy=f"{d.year % 100:02d}", yyyy=d.year, n=seq[pid])
    seq = {}
    for s in sorted(sets, key=lambda s: (s["carrier"], s["sailing_date"], s["set_id"])):
        pre, port = s["_carrier"][1], PORT_CODE[s["port_loading"].split(",")[0]]
        seq[pre] = seq.get(pre, rng.randint(lo, hi) * 100) + rng.randint(3, 40)
        s["bl_no"] = f"{pre}{port}{s['sailing_date'][2:4]}{seq[pre]:06d}"
    seq = {}
    for s in sorted((s for s in sets if s["co_form"]), key=lambda s: (s["co_form"], s["co_issue_date"], s["set_id"])):
        f, yy = s["co_form"], s["co_issue_date"][2:4]
        key = "CN" if f == "KCFTA" else "VN"                 # AK·VK는 같은 베트남 발급 시스템이라 번호를 같이 쓴다
        seq[key] = seq.get(key, rng.randint(lo, hi) * 10) + rng.randint(1, 30)
        if f == "KCFTA":
            s["co_no"] = f"K{yy}{PORT_CODE[s['port_loading'].split(',')[0]]}{seq[key]:07d}"
        else:
            s["co_no"] = f"VN-KR {yy}/{rng.choice(['02', '03', '04'])}/{seq[key]:05d}"   # VN-KR 연/발급처/번호 (발급처 번호는 가상)


def build_split(seed, split, prefix, n, error_rate, parties, items, test_consignees=()):
    """한 분할(개발용·발표용)을 만든다. 분할마다 난수를 따로 써서 서로 영향을 주지 않는다."""
    rng = random.Random(f"{seed}:{split}")
    n_err = round(n * error_rate)
    slots = allocate(rng, n_err) + [None] * (n - n_err)
    rng.shuffle(slots)
    sets = make_split(rng, split, prefix, slots, parties, items, list(test_consignees))
    pl = Planter(rng, {s["invoice_no"] for s in sets})
    planted, variants = Counter(), Counter()
    for s in sets:
        lines, t, slot = s["_lines"], s["_t"], s["_slot"]
        errors, var = [], []
        if slot in P0_FIELDS:
            errors.append(pl.p0(s, slot, lines, t))
        elif slot:
            got = {"sum": lambda: pl.sum(s, lines, t), "hs": lambda: pl.hs(s, lines),
                   "bl": lambda: pl.bl(s, t), "co": lambda: pl.co(s, lines)}[slot]()
            errors += got if isinstance(got, list) else [got]
        if slot and errors[0] and rng.random() < ERROR_RATE_SECOND:     # 오류 하나 더 (다른 칸)
            used = {e["field"] for e in errors}
            pool = [f for f in P0_FIELDS if f not in used and not (slot == "sum" and f == "total_gross_kg")]
            busy = {e["doc"] for e in errors if e["field"] in ("total_qty", "total_gross_kg")}
            field = rng.choice(pool)
            errors.append(pl.p0(s, field, lines, t, doc=("CI" if "PL" in busy else "PL") if busy else None))
        if slot and not all(errors):
            sys.exit(f"{s['set_id']}: {slot} 오류를 심지 못했어요")
        if not slot and rng.random() < VARIANT_RATE:
            v = pl.variant(s, lines, t)
            var = [v] if v else []
        for e in errors:
            planted[(e["doc"], e["field"].split(".")[-1], e["kind"])] += 1
        for v in var:
            variants[v["kind"]] += 1
        s["errors"] = json.dumps(errors, ensure_ascii=False) if errors else ""
        s["variants"] = json.dumps(var, ensure_ascii=False) if var else ""
        s["error_note"] = "; ".join(f"[{e['doc']} {e['field']}:{e['kind']}{'@' + str(e['line']) if e['line'] else ''}] "
                                    f"{e['orig']}→{e['value']}" for e in errors)
    return sets, planted, variants


def clean_old(split, sets):
    """그 분할의 새 세트에 없는 예전 서류 폴더를 지운다 (doc_a~doc_d 파일만 든 폴더만)."""
    keep, removed, d = {s["set_id"] for s in sets}, [], ROOT / "samples" / split
    for p in sorted(d.iterdir()) if d.exists() else []:
        if p.is_dir() and re.fullmatch(r"[A-Z]+\d+", p.name) and p.name not in keep \
                and all(re.fullmatch(r"doc_[a-d]", f.name.split(".")[0]) for f in p.iterdir()):
            shutil.rmtree(p)
            removed.append(f"{split}/{p.name}")
    return removed


def summary(split, sets, planted, variants):
    n_err = sum(1 for s in sets if s["errors"])
    n_two = sum(1 for s in sets if s["errors"].count('"doc"') > 1)
    print(f"  {split}: 세트 {len(sets)} · 정상 {len(sets) - n_err}(헷갈리는 차이 {sum(variants.values())}) · "
          f"오류 세트 {n_err}(오류 두 개 {n_two}) · 심은 오류 {sum(planted.values())}")
    by_doc = Counter()
    for (doc, field, kind), v in planted.items():
        by_doc[f"{doc} {field}"] += v
    print("    오류: " + ", ".join(f"{k} {v}" for k, v in sorted(by_doc.items())))
    print(f"    헷갈리는 차이: {dict(variants) or '-'}")
    print(f"    품목 줄 수 {dict(sorted(Counter(len(s['_lines']) for s in sets).items()))} · "
          f"원산지증명서 {dict(Counter(s['co_form'] or '없음' for s in sets))} · "
          f"서류 형식(송장·명세서) {dict(Counter(s['format'] for s in sets))}")


def load_catalog(name):
    rows = read(GEN / name) if (GEN / name).exists() else []
    if name.startswith("items"):
        for it in rows:
            for k in NUM:
                it[k] = float(it[k])
            it["hs_on_invoice"] = HS_PRINT[it["hs_print"]](it["hs10_answer"])
    return rows


def main():
    ap = argparse.ArgumentParser(description="규칙 기반 데이터셋 생성기")
    ap.add_argument("--dev", type=int, default=75, help="개발용 세트 수")
    ap.add_argument("--test", type=int, default=50, help="발표용 세트 수 (발표용을 새로 만들 때만 쓰임)")
    ap.add_argument("--error-rate", type=float, default=0.6, help="오류를 심는 세트 비율")
    ap.add_argument("--seed", type=int, default=6)
    ap.add_argument("--force-test", action="store_true", help="발표용 세트도 다시 만든다 (잠그기 전에만)")
    args = ap.parse_args()

    parties, items = load_catalog("parties.csv"), load_catalog("items.csv")
    t_parties, t_items = load_catalog("parties_test.csv"), load_catalog("items_test.csv")
    problems = check_hs(items + t_items)
    codes = [it["item_code"] for it in items + t_items]
    problems += [f"품목 코드 중복: {c}" for c, k in Counter(codes).items() if k > 1]
    pids = {p["party_id"] for p in parties + t_parties}
    problems += [f"{it['item_code']}: 수출자 {it['exporter_id']}가 거래처에 없음" for it in items + t_items
                 if it["exporter_id"] not in pids]
    if problems:
        sys.exit("카탈로그 검증 실패:\n  " + "\n  ".join(problems))

    write(DATA / "parties.csv", PARTY_COLUMNS, parties)
    write(DATA / "items.csv", ITEM_COLUMNS, [{**it, **{k: fmt_num(it[k]) for k in NUM}} for it in items])
    print(f"거래처 {len(parties)} · 품목 {len(items)} · 발표용 전용 거래처 {len(t_parties)} · 품목 {len(t_items)} · 시드 {args.seed}")

    dev, planted, variants = build_split(args.seed, "dev", "D", args.dev, args.error_rate, parties, items)
    write(DATA / "sets.csv", SET_COLUMNS, dev)
    removed = clean_old("dev", dev)
    summary("dev", dev, planted, variants)

    if TEST_FILE.exists() and not args.force_test:
        print("  test: 그대로 둠 (samples/data/sets_test.csv). 다시 만들려면 --force-test")
    elif LOCK_FILE.exists():
        sys.exit("발표용 세트가 잠겨 있어요 (samples/test_lock.json). 정말 다시 만들려면 잠금 파일을 먼저 지우세요.")
    else:
        if not t_items:
            print("  주의: 발표용 전용 품목(samples/gen/items_test.csv)이 없어 개발용 품목으로만 만들어요")
        test_cons = [p["party_id"] for p in t_parties if p["role"] == "consignee"]
        test, planted, variants = build_split(args.seed, "test", "T", args.test, args.error_rate,
                                              parties + t_parties, items + t_items, test_cons)
        write(TEST_FILE, SET_COLUMNS, test)
        write(DATA / "parties_test.csv", PARTY_COLUMNS, t_parties)
        write(DATA / "items_test.csv", ITEM_COLUMNS, [{**it, **{k: fmt_num(it[k]) for k in NUM}} for it in t_items])
        removed += clean_old("test", test)
        summary("test", test, planted, variants)
        print("  → 발표용 서류는 build_samples.py --test 로 만든다")
    if removed:
        print(f"  예전 서류 폴더 정리: {', '.join(removed)}")
    print("→ 다음: .venv/bin/python samples/build_samples.py")


if __name__ == "__main__":
    main()
