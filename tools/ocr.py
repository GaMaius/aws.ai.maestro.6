"""ocr_document. 담당: 서버. 규칙: .kiro/steering/agent-design.md 4번, 형식: docs/schema.md

OCR 자체는 Amazon Textract가 한다. 여기서는 호출하고 결과를 OcrResult로 바꾸기만 한다.
작업: e2e-plan.md B4 (P1). 권한(textract:AnalyzeDocument 등)은 infra/policy-*.json에 추가한다 (F4).
"""

from typing import Protocol

from tools.models import OcrResult


class TextractClient(Protocol):
    """boto3 textract 클라이언트에서 쓰는 부분만. 테스트에서는 가짜로 바꾼다."""

    def analyze_document(self, **kwargs) -> dict: ...


def ocr_document(file: str, data: bytes, *, client: TextractClient | None = None) -> OcrResult:
    """스캔본·사진 한 장을 Textract로 OCR한다.

    언제: 사진·스캔본을 읽을 때 함께 불러 두고, 다시 확인(reread_field)의 두 번째 근거로 쓴다.
    받는 것: file(S3 키), data(파일 바이트), client(테스트용 가짜 Textract).
    반환: OcrResult (글자 줄, 표, 좌표). 저장은 부른 쪽이 한다.
    타임아웃 5초, 재시도 1회. 실패하면 예외를 그대로 올린다 (부른 쪽이 '확인 필요(조회 못 함)').
    """
    print(f"[tool] ocr_document file={file} bytes={len(data)}")
    raise NotImplementedError("B4: Textract 호출 (서버 담당)")
