"""samples/measure_e2e.py(끝까지 측정, FB15 #172) 단위 테스트. 모델·AWS 호출 없음."""

import asyncio
from collections import Counter

from samples.measure_e2e import (
    LocalReadCache, cost_usd, count_model_usage, dev_sets, files_of, pick_sets, set_kind, summarize,
)


def test_pick_sets_is_ten_per_invoice_format_and_mixed():
    picked = pick_sets()
    sets, kinds = dev_sets(), set_kind()
    assert len(picked) == len(set(picked)) == 30 and picked == pick_sets()  # 늘 같은 30세트
    assert Counter(sets[s]["commercial_invoice"] for s in picked) == {"pdf": 10, "png": 10, "scan": 10}
    for fmt in ("pdf", "png", "scan"):  # 형식마다 심은 P0 오류·정상·헷갈리는 정상이 모두 들어 있다
        got = Counter(kinds[s] for s in picked if sets[s]["commercial_invoice"] == fmt)
        assert got["P0"] >= 4 and got["정상"] == 2 and got["변형"] == 2
    assert all(s.startswith("D") for s in picked)  # 개발용만 (발표용은 열지 않는다)


def test_files_of_lists_every_document_of_the_set():
    files = files_of("D003")
    assert [t for _, t in files] == ["commercial_invoice", "packing_list", "certificate_of_origin", "bill_of_lading"]
    assert files[0][0] == "samples/dev/D003/doc_a.pdf" and files[3][0].endswith("doc_d.pdf")


def test_local_read_cache_round_trip(tmp_path):
    cache = LocalReadCache(tmp_path / "read")
    assert cache.get("k1") is None
    cache.put("k1", '{"model": "RawDocument", "raw": {}}')
    assert cache.get("k1") == '{"model": "RawDocument", "raw": {}}'


def test_summarize_counts_by_format_without_model():
    """측정 줄 → 표. 탐지·읽기는 eval/score.py 함수로 센다 (D003 상업송장 총중량에 심은 오류를 짚은 줄 하나)."""
    row = {
        "set_id": "D003", "formats": dev_sets()["D003"], "status": "waiting_approval", "error": None,
        "seconds": 11.4, "model_calls": 10,
        "classified": [["doc_a.pdf", "commercial_invoice", True], ["doc_d.pdf", "bill_of_lading", False]],
        "docs": [{"doc_type": "commercial_invoice", "file": "samples/dev/D003/doc_a.pdf",
                  "total_gross_kg": {"raw": "21,683.10 KGS", "value": 21683.1, "unit": "KG"}}],
        "issues": [{"rule_id": "X-WT-01", "grade": "불일치", "evidence": "총중량이 다릅니다",
                    "cells": [{"doc": "commercial_invoice", "field": "total_gross_kg", "raw": "21,683.10 KGS"},
                              {"doc": "packing_list", "field": "total_gross_kg", "raw": "12,683.10 KGS"}]}],
        "hs": [{"line": 1, "status": "사람 확인 필요"}], "steps": [],
    }
    s = summarize([row, {**row, "set_id": "D005", "formats": dev_sets()["D005"], "issues": [], "docs": [],
                         "tokens_in": 30_000, "tokens_out": 4_000}])  # 토큰 칸이 있는 줄과 없는 예전 줄
    assert s["tokens"]["tokens_in"] == 30_000 and s["tokens"]["per_set_in"] == 15_000
    assert s["cost_usd"]["total"] == cost_usd(30_000, 4_000) == 0.1 and s["cost_usd"]["per_set"] == 0.05
    s = summarize([row])
    assert s["sets"] == 1 and s["model_calls"] == 10 and s["hs"] == {"사람 확인 필요": 1}
    assert s["classify_by_format"] == {"pdf": {"분류": 1, "분류 맞음": 1}, "scan": {"분류": 1, "분류 맞음": 0}}
    assert (s["detection"]["planted"], s["detection"]["detected"]) == (1, 1)
    assert s["seconds"] == {"mean": 11.4, "max": 11.4}


def test_count_model_usage_reads_bedrock_usage_metadata(monkeypatch):
    """BedrockModel.stream 응답 끝의 metadata.usage에서 토큰을 모은다 (실제 Bedrock 호출 없음)."""
    from strands.models import bedrock

    async def fake_stream(self, *args, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        yield {"metadata": {"usage": {"inputTokens": 3500, "outputTokens": 130, "totalTokens": 3630}}}

    monkeypatch.setattr(bedrock.BedrockModel, "stream", fake_stream)  # 끝나면 진짜 stream으로 되돌린다
    usage = count_model_usage()

    async def call_twice():
        for _ in range(2):
            async for _event in bedrock.BedrockModel.stream(None):
                pass

    asyncio.run(call_twice())
    assert usage == {"model": 2, "tokens_in": 7000, "tokens_out": 260, "cache_read": 0, "cache_write": 0}
    assert cost_usd(7000, 260) == round((7000 * 2 + 260 * 10) / 1_000_000, 4)
