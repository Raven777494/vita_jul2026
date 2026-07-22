"""
Round 30 / P8.0＋P8.1 — 通過定義與四類固定腳本庫
- 庫結構／最低數量
- VAD signed
- contract：童年／危機／閒聊 guidance 裁判
- fixture：衝突壞初稿修復
- Zero-Truncation：soul content 完整；format_memory_by_mood 不硬截
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_p80_pass_definition_present():
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    pd = lib.P8_PASS_DEFINITION
    assert pd["version"] == lib.P8_VERSION
    assert "passed" in pd["status_values"]
    assert "passed_degraded" in pd["status_values"]
    assert pd["zero_truncation"]["max_memory_snippet_chars"] == 0
    assert "ABCD" in str(pd["out_of_scope"])


def test_p81_library_min_counts_and_unique_ids():
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    ok, notes = lib.validate_scenario_library()
    assert ok, notes
    summary = lib.library_public_summary()
    assert summary["suite_counts"]["childhood"] >= 3
    assert summary["suite_counts"]["crisis"] >= 2
    assert summary["suite_counts"]["chat"] >= 2
    assert summary["suite_counts"]["conflict"] >= 3
    assert len(summary["scenario_ids"]) == len(set(summary["scenario_ids"]))


def test_p81_filter_suite():
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    childhood = lib.filter_scenarios("childhood")
    assert all(s["suite"] == "childhood" for s in childhood)
    assert len(childhood) >= 3
    conflict = lib.filter_scenarios("conflict", kind="bad_draft")
    assert all(s["kind"] == "bad_draft" for s in conflict)


def test_p81_contract_childhood_crisis_chat_soul_gates():
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    p6 = p8._load_p6()
    module = p6._build_module()

    for sc in lib.live_scenarios():
        g = module.prepare_draft_guidance(
            user_input=sc["user"],
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={
                "user_sentiment": sc["sentiment"],
                "risk_level": sc["risk"],
            },
        )
        ok, notes = p6.judge_guidance(g, sc["expect"])
        assert ok, (sc["id"], notes, g.get("soul_memory_id"), g.get("intensity"))
        # Zero-Truncation
        soul = g.get("soul_memory")
        if isinstance(soul, dict) and soul.get("content"):
            assert soul["content"] in g["system_prompt"]


def test_p81_fixture_conflict_and_full_fixture_mode(tmp_path):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")

    class Args:
        mode = "fixture"
        suite = "all"
        url = ""
        model = ""
        out = str(tmp_path / "p8_report.json")

    code = asyncio.run(p8.async_main(Args()))
    assert code == 0
    report = Path(Args.out).read_text(encoding="utf-8")
    assert '"status": "passed"' in report
    assert "C1_past_fan_tong_lau" in report
    assert "CR1_want_die_quiet" in report
    assert "CH1_tired_presence" in report
    assert "CF1_hotline_scrub" in report


def test_p81_format_memory_by_mood_zero_truncation():
    from PersonalityModule.island_fusion import IslandFusion

    fusion = IslandFusion(
        data_dir=str(ROOT / "PersonalityModule" / "data")
    )
    long_body = "風扇聲同舊唐樓。" * 20
    assert len(long_body) > 100
    weaved = fusion.format_memory_by_mood(long_body, "Empath", 0.3)
    assert long_body in weaved or weaved.endswith(long_body) or long_body[:50] in weaved
    assert "…" not in weaved[-3:] or long_body in weaved
    # 硬截斷舊行為：content[:97]+… 不得再出現為唯一正文
    assert not (len(weaved) <= 120 and weaved.rstrip().endswith("…") and long_body not in weaved)
