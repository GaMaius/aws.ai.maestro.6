"""Textract 대신 쓰는 로컬 OCR (docs/REBUILD.md M2).

- PDF에 글자층이 있으면(생성한 서류) OCR 하지 않고 글자층의 글자 조각과 위치를 그대로 쓴다 (pypdfium2).
  화면의 쪽 그림도 같은 PDF 쪽을 그린 것이라 위치(0~1 비율)가 그대로 맞는다.
- 사진·스캔한 PDF는 Tesseract(kor+eng)가 있으면 읽는다. 없으면 글자 줄 없이 돌려준다.
  OCR 은 다시 확인의 두 번째 근거와 칸 위치에만 쓰이므로, 없어도 판독·대조는 그대로 진행된다 (api/worker.py).

반환 모양은 tools.ocr.ocr_document 와 같다 (OcrResult).
"""

from __future__ import annotations

import io
import os
import shutil

from tools.models import OcrLine, OcrResult
from tools.ocr import MAX_PAGES, PDFIUM_LOCK, is_pdf, render_pages


def pdf_text_lines(data: bytes, max_pages: int = MAX_PAGES) -> list[OcrLine]:
    """PDF 글자층의 글자 조각마다 쪽 번호·글자·위치. 글자층이 없으면 빈 목록."""
    import pypdfium2 as pdfium

    with PDFIUM_LOCK:
        return _pdf_text_lines(pdfium, data, max_pages)


def _pdf_text_lines(pdfium, data: bytes, max_pages: int) -> list[OcrLine]:
    pdf = pdfium.PdfDocument(data)
    lines: list[OcrLine] = []
    try:
        for number in range(1, min(len(pdf), max_pages) + 1):
            page = pdf[number - 1]
            width, height = page.get_size()
            textpage = page.get_textpage()
            for i in range(textpage.count_rects()):
                left, bottom, right, top = textpage.get_rect(i)
                text = " ".join(textpage.get_text_bounded(left, bottom, right, top).split())
                if not text or width <= 0 or height <= 0:
                    continue
                bbox = (left / width, (height - top) / height, (right - left) / width, (top - bottom) / height)
                lines.append(OcrLine(page=number, text=text, bbox=tuple(round(max(0.0, min(1.0, v)), 4) for v in bbox)))
    finally:
        pdf.close()
    return lines


def tesseract_available() -> bool:
    """pytesseract 와 tesseract 실행 파일이 모두 있는지. TESSERACT_CMD 로 실행 파일 위치를 줄 수 있다."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("TESSERACT_CMD") or shutil.which("tesseract"))


def tesseract_lines(image_bytes: bytes, page: int) -> list[OcrLine]:
    """그림 한 장을 Tesseract 로 읽어 줄마다 글자·위치. 언어는 OCR_LANG(기본 kor+eng)."""
    import pytesseract
    from PIL import Image

    if os.environ.get("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
    with Image.open(io.BytesIO(image_bytes)) as img:
        image = img.convert("RGB")
    width, height = image.size
    data = pytesseract.image_to_data(image, lang=os.environ.get("OCR_LANG", "kor+eng"), output_type=pytesseract.Output.DICT)
    groups: dict[tuple[int, int, int], list[int]] = {}
    for i, word in enumerate(data["text"]):
        if word.strip() and float(data["conf"][i]) >= 0:
            groups.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
    lines = []
    for idx in groups.values():
        left = min(data["left"][i] for i in idx)
        top = min(data["top"][i] for i in idx)
        right = max(data["left"][i] + data["width"][i] for i in idx)
        bottom = max(data["top"][i] + data["height"][i] for i in idx)
        text = " ".join(data["text"][i].strip() for i in idx)
        lines.append(OcrLine(page=page, text=text, bbox=(left / width, top / height, (right - left) / width, (bottom - top) / height)))
    return lines


def local_ocr_document(file: str, data: bytes, *, client=None, pages: list[bytes] | None = None) -> OcrResult:
    """tools.ocr.ocr_document 대신 (같은 인자). client 는 받지만 쓰지 않는다."""
    print(f"[tool] ocr_document(local) file={file} bytes={len(data)}")
    if is_pdf(file):
        lines = pdf_text_lines(data)
        if lines:
            print(f"[tool] ocr_document(local) file={file} PDF 글자층 {len(lines)}조각")
            return OcrResult(file=file, lines=lines)
    if not tesseract_available():
        print(f"[tool] ocr_document(local) file={file} Tesseract가 없어 OCR 없이 진행 (local/README.md)")
        return OcrResult(file=file, lines=[])
    if pages is None:
        pages = [p.data for p in render_pages(data)] if is_pdf(file) else [data]
    lines = [line for number, page in enumerate(pages, start=1) for line in tesseract_lines(page, number)]
    print(f"[tool] ocr_document(local) file={file} Tesseract 쪽 {len(pages)}, 줄 {len(lines)}개")
    return OcrResult(file=file, lines=lines)
