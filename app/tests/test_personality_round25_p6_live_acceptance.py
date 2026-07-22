"""
Round 25 / P6 真機對話驗收 — 裁判與 fixture 路徑單元測試（無需 LLM）
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "seele_live_dialogue_acceptance.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("seele_live_dialogue_acceptance", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_p6_judge_guidance_past_and_crisis():
    mod = _load_script()
    g_ok = {
        "soul_memory_id": "memory_01",
        "intensity": "medium",
        "prompt_contract": "pre_draft_full_no_truncation",
        "system_prompt": "風扇\nNo institutional hotline/ER scripts.\n" + ("x" * 120),
        "soul_memory": {"content": "風扇"},
    }
    ok, notes = mod.judge_guidance(
        g_ok,
        {"soul_id": "memory_01", "past": True, "no_hotline": True},
    )
    assert ok, notes

    g_bad = dict(g_ok)
    g_bad["system_prompt"] = "請打自殺熱線\n" + ("x" * 120)
    ok2, notes2 = mod.judge_guidance(g_bad, {"no_hotline": True})
    assert not ok2
    assert any("hotline" in n for n in notes2)


def test_p6_judge_final_scrub_expectations():
    mod = _load_script()
    ok, notes = mod.judge_final_text(
        "我想先誠實核對一下。我喺度陪住你。",
        {"no_hotline": True, "no_denial": True, "min_chars": 10},
        draft="我冇講錯過，你亂講。你快啲打自殺熱線。",
    )
    assert ok, notes

    ok2, notes2 = mod.judge_final_text(
        "你快啲打自殺熱線同打999。",
        {"no_hotline": True, "repaired_or_scrubbed": True},
        draft="你快啲打自殺熱線同打999。",
    )
    assert not ok2


def test_p6_fixture_mode_pipeline_passes(tmp_path):
    import asyncio

    mod = _load_script()

    class Args:
        mode = "fixture"
        url = ""
        model = ""
        out = str(tmp_path / "p6_report.json")

    code = asyncio.run(mod.async_main(Args()))
    assert code == 0
    report = Path(Args.out).read_text(encoding="utf-8")
    assert '"status": "passed"' in report or '"status": "passed_degraded"' in report
    assert "L3_crisis_quiet" in report
    assert "B1_hotline_scrub" in report


def test_p6_live_mode_exits_2_when_llm_down(tmp_path, monkeypatch):
    import asyncio

    mod = _load_script()
    monkeypatch.setattr(mod, "probe_llm_service", lambda url, timeout=3.0: (False, "down"))

    class Args:
        mode = "live"
        url = "http://127.0.0.1:9"
        model = ""
        out = str(tmp_path / "p6_live_down.json")

    code = asyncio.run(mod.async_main(Args()))
    assert code == 2
