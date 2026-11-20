"""선하증권(B/L)과 원산지증명서를 PDF로 그리고, 서류를 스캔본처럼 만든다. build_samples.py 가 부른다.

B/L: 운송사 양식처럼 칸을 나누고 자료는 고정폭 글꼴(Courier)로 찍는다. 품명은 일반 명칭, 무게는 소수 셋째 자리.
원산지증명서: 한-중 FTA 서식, 한-아세안(AK)·한-베트남(VK) FTA 서식의 칸 구성을 따른다.
스캔본: 그림으로 바꾼 뒤 기울기·흐림·잡티·압축을 넣고 글자층 없는 PDF로 저장한다.
모든 서류에 SAMPLE 표시를 찍는다. 값은 build_samples.py 가 넘겨준 글자를 그대로 쓴다 (여기서 값을 만들지 않는다).
"""
import hashlib, io, random, subprocess, tempfile
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4
MM = 72 / 25.4
SAMPLE_LINE = "SAMPLE FOR TESTING ONLY - NOT A REAL DOCUMENT"


# ── 그리기 도구 ──────────────────────────────────────────────────────────────
class Sheet:
    """위쪽 왼쪽을 (0,0)으로 mm 단위로 그린다."""

    def __init__(self, path, title):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.c.setTitle(title)
        self.c.setAuthor("SAMPLE")

    def box(self, x, y, w, h, lw=0.6):
        self.c.setLineWidth(lw)
        self.c.rect(x * MM, H - (y + h) * MM, w * MM, h * MM)

    def line(self, x1, y1, x2, y2, lw=0.6):
        self.c.setLineWidth(lw)
        self.c.line(x1 * MM, H - y1 * MM, x2 * MM, H - y2 * MM)

    def text(self, x, y, s, size=8, font="Courier", right=False, center=False):
        self.c.setFont(font, size)
        fn = self.c.drawRightString if right else self.c.drawCentredString if center else self.c.drawString
        fn(x * MM, H - y * MM, str(s))

    def label(self, x, y, s, size=5.6):
        self.text(x, y, s, size=size, font="Helvetica")

    def lines(self, x, y, rows, size=8, font="Courier", lead=None, width=None):
        """여러 줄. width(mm)를 주면 넘치는 줄을 낱말 단위로 꺾는다. 쓴 줄 수를 돌려준다."""
        lead = lead or size * 0.45
        out = []
        for r in rows:
            out += wrap(str(r), width, size, font) if width else [str(r)]
        for i, r in enumerate(out):
            self.text(x, y + i * lead, r, size, font)
        return len(out)

    def watermark(self, word="SAMPLE"):
        c = self.c
        c.saveState()
        c.setFillGray(0.88)
        c.setFont("Helvetica-Bold", 96)
        c.translate(W / 2, H / 2)
        c.rotate(35)
        c.drawCentredString(0, -30, word)
        c.restoreState()

    def footer(self):
        self.text(105, 290, SAMPLE_LINE, size=9, font="Helvetica-Bold", center=True)

    def save(self):
        self.c.showPage()
        self.c.save()


def wrap(text, width_mm, size, font):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    out, cur = [], ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if stringWidth(cand, font, size) / MM <= width_mm or not cur:
            cur = cand
        else:
            out.append(cur)
            cur = word
    return out + ([cur] if cur else [])


ONES = "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE THIRTEEN FOURTEEN FIFTEEN SIXTEEN " \
       "SEVENTEEN EIGHTEEN NINETEEN".split()
TENS = "_ _ TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY".split()


def words(n):
    """포장 수를 영어로 (B/L의 'SAY ... ONLY')."""
    n = int(n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else "-" + ONES[n % 10])
    if n < 1000:
        return ONES[n // 100] + " HUNDRED" + ("" if n % 100 == 0 else " " + words(n % 100))
    return words(n // 1000) + " THOUSAND" + ("" if n % 1000 == 0 else " " + words(n % 1000))


# ── 선하증권 ────────────────────────────────────────────────────────────────
def bl_pdf(path, b):
    """b: build_samples.bl_data() 가 만든 글자들."""
    s = Sheet(path, "BILL OF LADING")
    s.watermark()
    s.text(10, 13, b["carrier"], size=12, font="Helvetica-Bold")
    s.text(10, 18, "OCEAN TRANSPORT  ·  SAMPLE CARRIER FOR TESTING", size=6.5, font="Helvetica")
    s.text(200, 13, "BILL OF LADING", size=16, font="Helvetica-Bold", right=True)
    s.text(200, 18, "FOR COMBINED TRANSPORT OR PORT TO PORT SHIPMENT", size=6, font="Helvetica", right=True)

    # 위쪽: 송하인·수하인·통지처 | B/L 번호·약관
    s.box(10, 22, 95, 30); s.label(11.5, 25, "SHIPPER / EXPORTER")
    s.lines(12, 29, b["shipper"], size=7.6, width=91)
    s.box(10, 52, 95, 28); s.label(11.5, 55, "CONSIGNEE")
    s.lines(12, 59, b["consignee"], size=7.6, width=91)
    s.box(10, 80, 95, 26); s.label(11.5, 83, "NOTIFY PARTY (CARRIER NOT TO BE RESPONSIBLE FOR FAILURE TO NOTIFY)")
    s.lines(12, 87, b["notify"], size=7.6, width=91)
    s.box(105, 22, 95, 14)
    s.label(106.5, 25, "B/L NO."); s.text(107, 31, b["bl_no"], size=11, font="Courier-Bold")
    s.label(160, 25, "BOOKING NO."); s.text(160, 31, b["booking_no"], size=8)
    s.box(105, 36, 95, 16); s.label(106.5, 39, "EXPORT REFERENCES")
    s.lines(107, 43, b["refs"], size=7.4, width=91)
    s.box(105, 52, 95, 54)
    s.lines(107, 56, [b["clause"]], size=5.4, font="Helvetica", width=90, lead=2.5)
    s.label(106.5, 91, "DELIVERY AGENT AT DESTINATION")
    s.lines(107, 95, b["agent"], size=7.4, width=91)

    # 운송 칸
    cells = [("PRE-CARRIAGE BY", b["pre_carriage"]), ("PLACE OF RECEIPT", b["receipt"]),
             ("OCEAN VESSEL / VOY. NO.", b["vessel"]), ("PORT OF LOADING", b["pol"]),
             ("PORT OF DISCHARGE", b["pod"]), ("PLACE OF DELIVERY", b["delivery"]),
             ("FINAL DESTINATION", b["final_dest"]), ("TYPE OF MOVEMENT", b["service"])]
    for i, (lab, val) in enumerate(cells):
        x, y = 10 + (i % 4) * 47.5, 106 + (i // 4) * 11
        s.box(x, y, 47.5, 11); s.label(x + 1.5, y + 3, lab); s.text(x + 2, y + 8.3, val, size=7.4)

    # 화물 표
    top, bottom = 128, 230
    cols = [(10, "CONTAINER NO. / SEAL NO.", "MARKS & NUMBERS"), (58, "NO. OF", "PKGS"),
            (75, "KIND OF PACKAGES; DESCRIPTION OF GOODS", "(PARTICULARS FURNISHED BY SHIPPER)"),
            (150, "GROSS WEIGHT", "(KGS)"), (175, "MEASUREMENT", "(CBM)")]
    s.box(10, top, 190, bottom - top)
    s.line(10, top + 8, 200, top + 8)
    for x, l1, l2 in cols:
        if x > 10:
            s.line(x, top, x, bottom - 22)
        s.label(x + 1.5, top + 3.2, l1); s.label(x + 1.5, top + 6.4, l2)
    y0 = top + 13
    s.lines(11.5, y0, b["marks"], size=7.2, width=45)
    s.text(60, y0, b["packages"], size=8); s.text(60, y0 + 4, b["package_kind"], size=7.2)
    used = s.lines(76.5, y0, b["description"], size=7.4, width=72)
    s.text(173, y0, b["gross"], size=8, right=True)
    s.text(198, y0, b["cbm"], size=8, right=True)
    # 컨테이너 명세
    cy = y0 + max(used, len(b["marks"])) * 3.4 + 4
    s.label(11.5, cy, "CONTAINER DETAILS: CONTAINER NO. / SEAL NO. / SIZE-TYPE / PACKAGES / GROSS WEIGHT / MEASUREMENT")
    s.lines(11.5, cy + 4, b["containers"], size=7.2, lead=3.4)
    s.line(10, bottom - 22, 200, bottom - 22)
    s.label(11.5, bottom - 18.5, "TOTAL NUMBER OF CONTAINERS OR PACKAGES (IN WORDS)")
    s.text(12, bottom - 13.5, b["say"], size=7.6)
    s.label(11.5, bottom - 8, "FREIGHT & CHARGES")
    s.text(45, bottom - 8, b["freight"], size=8, font="Courier-Bold")
    s.text(120, bottom - 8, b["freight_at"], size=7.4)

    # 아래쪽: 원본 수, 발행지·일자, 선적일, 서명
    s.box(10, 230, 63, 12); s.label(11.5, 233, "NUMBER OF ORIGINAL B(S)/L"); s.text(12, 239, b["originals"], size=7.6)
    s.box(73, 230, 64, 12); s.label(74.5, 233, "PLACE AND DATE OF ISSUE"); s.text(75, 239, b["issued"], size=7.6)
    s.box(137, 230, 63, 12); s.label(138.5, 233, "SHIPPED ON BOARD THE VESSEL"); s.text(139, 239, b["onboard"], size=7.6)
    s.box(10, 242, 190, 34)
    s.lines(12, 246, ["IN WITNESS whereof the number of original Bills of Lading stated above have been signed, one of "
                      "which being accomplished, the others to stand void. SAMPLE TERMS FOR TESTING ONLY."],
            size=5.6, font="Helvetica", width=110, lead=2.6)
    s.text(195, 258, f"FOR {b['carrier']}", size=7.4, font="Helvetica-Bold", right=True)
    s.text(195, 268, "SAMPLE SIGNATURE", size=9, font="Times-Italic", right=True)
    s.line(140, 270, 196, 270, lw=0.4)
    s.text(195, 273.5, "AS CARRIER", size=7, font="Helvetica", right=True)
    s.footer()
    s.save()


# ── 원산지증명서 ────────────────────────────────────────────────────────────
# 칸 구성: 한-중 FTA 부속서 3-C (2022-06-12 시행 서식, 14칸), 한-아세안 Form AK·한-베트남 Form VK (13칸)
CO_TITLE = {
    "KCFTA": ("CERTIFICATE OF ORIGIN", "Form for China-Korea FTA", "Issued in THE PEOPLE'S REPUBLIC OF CHINA"),
    "AK": ("ASEAN-KOREA FREE TRADE AREA PREFERENTIAL TARIFF", "CERTIFICATE OF ORIGIN (Combined Declaration and Certificate)",
           "FORM AK  ·  Issued in VIET NAM"),
    "VK": ("KOREA-VIET NAM FREE TRADE AGREEMENT", "CERTIFICATE OF ORIGIN", "FORM VK  ·  Issued in VIET NAM"),
}


def co_pdf(path, c):
    """c: build_samples.co_data() 가 만든 글자들. 한-중 FTA(14칸)와 AK·VK(13칸)는 칸 번호와 이름이 다르다."""
    form = c["form"]
    s = Sheet(path, "CERTIFICATE OF ORIGIN")
    s.watermark()
    t1, t2, t3 = CO_TITLE[form]
    kc = form == "KCFTA"
    # 왼쪽 칸: 수출자, (한-중) 생산자, 수하인, 운송 (AK·VK는 선적항 줄이 없다)
    if kc:
        left = [("1. Exporter's name, address and country", c["exporter"], 26),
                ("2. Producer's name and address, if known", c["producer"], 18),
                ("3. Consignee's name, address and country", c["consignee"], 26),
                ("4. Means of transport and route (as far as known)", c["transport"], 28)]
    else:
        left = [("1. Goods consigned from (Exporter's business name, address, country)", c["exporter"], 28),
                ("2. Goods consigned to (Consignee's name, address, country)", c["consignee"], 28),
                ("3. Means of transport and route (as far as known)", c["transport"], 30)]
    y = 12
    for lab, rows, h in left:
        s.box(10, y, 100, h); s.label(11.5, y + 3, lab)
        s.lines(12, y + 7, rows, size=7.4, width=96)
        y += h
    # 오른쪽 칸: 번호와 제목, 그 아래 (한-중) 5. 비고 또는 (AK·VK) 4. 수입국 세관용
    head = 46 if kc else 40
    s.box(110, 12, 90, head)
    s.label(111.5, 15, "Certificate No." if kc else "Reference No.")
    s.text(113, 21, c["co_no"], size=10, font="Courier-Bold")
    s.text(155, 30, t1, size=12 if kc else 8.4, font="Helvetica-Bold", center=True)
    s.lines(113, 36, [t2], size=7.4, font="Helvetica-Bold", width=84)
    s.text(155, 47 if kc else 45, t3, size=7.4, font="Helvetica", center=True)
    s.text(155, 53 if kc else 50, "(SAMPLE FORM FOR TESTING)", size=6.5, font="Helvetica", center=True)
    s.box(110, 12 + head, 90, y - 12 - head)
    if kc:
        s.label(111.5, 15 + head, "5. Remarks")
        s.lines(113, 21 + head, c["remarks"], size=7.6, font="Courier-Bold", width=85)
    else:
        s.label(111.5, 15 + head, "4. For Official Use")
        s.lines(113, 21 + head, ["[ ] Preferential Treatment Given Under ASEAN-Korea / Korea-Viet Nam FTA",
                                 "[ ] Preferential Treatment Not Given (Please state reason/s)", "",
                                 "....................................................",
                                 "Signature of Authorised Signatory of the Importing Party"],
                size=6.0, font="Helvetica", lead=3.2, width=85)
    # 품목 표
    top = y
    if kc:
        cols = [(10, 12, "6. Item", "number"), (22, 30, "7. Marks and", "numbers"), (52, 64, "8. Number and kind of packages;", "description of goods"),
                (116, 18, "9. HS code", "(Six-digit code)"), (134, 16, "10. Origin", "criterion"), (150, 24, "11. Gross weight,", "quantity or other measures"),
                (174, 26, "12. Number and", "date of invoice")]
    else:
        cols = [(10, 12, "5. Item", "number"), (22, 28, "6. Marks and numbers", "on packages"), (50, 70, "7. Number and type of packages, description of goods",
                "(incl. quantity and HS number of the importing Party)"), (120, 18, "8. Origin", "criterion"), (138, 30, "9. Gross weight or other",
                "quantity, and value (FOB) if RVC"), (168, 32, "10. Number and date", "of invoices")]
    body_h = 74
    s.box(10, top, 190, body_h)
    s.line(10, top + 8, 200, top + 8)
    for x, w, l1, l2 in cols:
        if x > 10:
            s.line(x, top, x, top + body_h)
        s.label(x + 1, top + 3.2, l1, size=5.2); s.label(x + 1, top + 6.4, l2, size=5.2)
    ry = top + 12.5
    s.lines(23, ry, c["marks"], size=6.6, width=cols[1][1] - 2, lead=3.0)
    for it in c["items"]:
        x_desc, w_desc = cols[2][0] + 1, cols[2][1] - 2
        s.text(14, ry, it["no"], size=7.4)
        n = s.lines(x_desc, ry, it["desc"], size=6.8, width=w_desc, lead=3.1)
        if kc:
            s.text(cols[3][0] + 1.5, ry, it["hs"], size=7.4)
            s.text(cols[4][0] + 1.5, ry, it["criterion"], size=7.4)
            s.lines(cols[5][0] + 1, ry, it["quantity"], size=6.6, width=cols[5][1] - 2, lead=3.0)
        else:
            s.text(cols[3][0] + 1.5, ry, it["criterion"], size=7.4)
            s.lines(cols[4][0] + 1, ry, it["quantity"], size=6.6, width=cols[4][1] - 2, lead=3.0)
        ry += max(n, 3) * 3.1 + 3
    s.lines(cols[-1][0] + 1, top + 12.5, c["invoice"], size=6.8, width=cols[-1][1] - 2, lead=3.0)
    s.text(cols[2][0] + cols[2][1] / 2, top + body_h - 3, "*** NO MORE ITEMS ***", size=6.5, center=True)
    # 신고(한-중 13, AK·VK 11)와 증명(한-중 14, AK·VK 12)
    y = top + body_h
    s.box(10, y, 95, 46); s.box(105, y, 95, 46)
    s.label(11.5, y + 3, "13. Declaration by the exporter" if kc else "11. Declaration by the exporter")
    s.lines(12, y + 7, [f"The undersigned hereby declares that the above details and statements are correct, that all the "
                        f"goods were produced in {c['origin_country']} (Country) and that they comply with the origin "
                        f"requirements specified in the {c['agreement']} for the goods exported to {c['importing_country']} "
                        f"(Importing Country)."], size=6.0, font="Helvetica", width=90, lead=2.7)
    s.text(12, y + 30, c["declaration_place_date"], size=7.2)
    s.text(12, y + 37, "SAMPLE SIGNATURE", size=8, font="Times-Italic")
    s.label(12, y + 42, "Place and date, signature of authorised signatory")
    s.label(106.5, y + 3, "14. Certification" if kc else "12. Certification")
    s.lines(107, y + 7, ["It is hereby certified, on the basis of control carried out, that the declaration by the exporter "
                         "is correct."], size=6.0, font="Helvetica", width=90, lead=2.7)
    s.text(107, y + 20, c["authority"], size=7.0, font="Helvetica-Bold")
    if c.get("retro") and not kc:                    # AK·VK는 소급 발급 표시를 증명 칸에 찍는다
        s.text(150, y + 26, "ISSUED RETROACTIVELY", size=8, font="Courier-Bold", center=True)
    s.text(107, y + 32, c["certified_place_date"], size=7.2)
    s.text(107, y + 38, "SAMPLE STAMP", size=8, font="Times-Italic")
    s.label(107, y + 43, "Place and date, signature and stamp of certifying authority")
    if not kc:
        y2 = y + 46
        s.box(10, y2, 190, 14)
        if form == "AK":
            s.label(11.5, y2 + 3, "13. Tick where appropriate")
            s.lines(12, y2 + 8, ["[ ] Third Country Invoicing      [ ] Exhibition      [ ] Back-to-Back CO"],
                    size=6.8, font="Helvetica")
        else:
            s.label(11.5, y2 + 3, "13. Remarks")
            s.lines(12, y2 + 8, c["remarks"] or [""], size=7.0)
    s.footer()
    s.save()


# ── 스캔본 ──────────────────────────────────────────────────────────────────
def scanify(pdf_in, pdf_out, seed, dpi=200):
    """PDF 첫 장을 그림으로 그려 스캔한 것처럼 만든 뒤, 글자층 없는 PDF로 저장한다.
    흑백 70%, 기울기 ±1.2°, 흐림, 잡티, 밝기 고르지 않음, JPEG 압축. 같은 seed면 같은 결과."""
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", str(pdf_in), f"{tmp}/p"], check=True)
        im = Image.open(f"{tmp}/p.png").convert("RGB")
    gray = rng.random() < 0.7
    if gray:
        im = im.convert("L")
    else:                                            # 누런 종이
        paper = Image.new("RGB", im.size, (rng.randint(240, 252), rng.randint(236, 246), rng.randint(214, 232)))
        im = Image.composite(im, paper, im.convert("L").point(lambda v: 255 - v))
    fill = 250 if gray else (248, 244, 230)
    im = im.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, fillcolor=fill,
                   translate=(rng.randint(-12, 12), rng.randint(-12, 12)))
    im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0.35, 0.8)))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.8, 1.05))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.95, 1.04))
    a = np.asarray(im).astype(np.float32)
    nr = np.random.default_rng(int(hashlib.md5(str(seed).encode()).hexdigest()[:12], 16))
    h, w = a.shape[:2]
    shade = np.linspace(rng.uniform(-14, 0), rng.uniform(0, 10), w)[None, :]      # 한쪽이 어두운 조명
    a += (shade if a.ndim == 2 else shade[..., None]) + nr.normal(0, rng.uniform(4, 9), a.shape)
    dots = nr.random((h, w)) < rng.uniform(0.0002, 0.0008)                         # 먼지 점
    a[dots] = nr.uniform(40, 120, int(dots.sum()))[:, None] if a.ndim == 3 else nr.uniform(40, 120, int(dots.sum()))
    edge = rng.randint(6, 18)                                                       # 스캐너 덮개 그림자
    a[:, :edge] *= 0.55
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=rng.randint(45, 70))
    Image.open(io.BytesIO(buf.getvalue())).save(pdf_out, "PDF", resolution=dpi)
    return Path(pdf_out)
