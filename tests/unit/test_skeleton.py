"""협업 뼈대 확인: 모든 모듈이 import되고, 메모리 구현이 약속한 모양대로 움직인다."""

import importlib
from datetime import date

import pytest

from tests.unit.fakes import MemoryHSHistory, MemoryShipments, MemoryWms
from tools.models import JobState, Shipment, WmsRecord

MODULES = [
    "agent", "agent.document_agent", "agent.query_agent", "api.handler",
    "tools.models", "tools.extract", "tools.ocr", "tools.validate", "tools.reread",
    "tools.hs", "tools.declaration", "tools.wms", "tools.query", "tools.report", "eval.score",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_memory_hs_history():
    history = MemoryHSHistory()
    assert history.get("샘플무역", "BP-200") is None
    history.put("샘플무역", "BP-200", "8507600000", "job-1")
    assert history.get("샘플무역", "BP-200") == "8507600000"


def test_memory_wms_is_idempotent():
    wms = MemoryWms()
    record = WmsRecord(idempotency_key="BL-1+job-1", bl_no="BL-1", job_id="job-1", consignee="샘플무역", by="auto")
    assert wms.register(record) == wms.register(record)
    assert len(wms.records) == 1


def test_memory_shipments():
    row = Shipment(bl_no="BL-1", consignee="샘플무역", item="배터리", arrived_at=date(2026, 11, 17),
                   customs_status="심사 중", last_event_at=date(2026, 11, 18))
    assert MemoryShipments([row]).all() == [row]


def test_job_state_starts_empty():
    state = JobState(job_id="job-1", files=["uploads/s1/a.pdf"])
    assert state.docs == {} and state.read_seq == state.check_seq == 0
