"""
Round 31 / P8.2 — 裁判＋echo_write／ZT／重複修復
- echo_write_trace 在 anchor 回傳前可讀
- conflict_repair 軟句不重複
- Heretic／Vocal 不再注入國語粒子／逗號省略號 spam
- P8 fixture 裁判含 echo_write + ZT row
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
DATA = str(ROOT / "PersonalityModule" / "data")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_p82_echo_write_trace_on_anchor_return():
    from PersonalityModule.personality_module import PersonalityModule

    module = PersonalityModule(
        config={"data_dir": DATA, "data_path": DATA, "max_memory_snippet_chars": 0}
    )
    module.setup_dependencies({})

    async def _run():
        final, state = await module.anchor(
            draft_response="我喺度陪住你。",
            user_input="我好攰",
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={
                "user_sentiment": {"valence": -0.2, "arousal": 0.4, "vad_scale": "signed"},
                "risk_level": 0,
                "skip_echo_consolidation": True,
                "orchestrator_hints": {"skip_echo_consolidation": True},
                "pre_draft_guidance": {"system_prompt": "x", "intensity": "medium"},
                "personality_system_prompt": "x",
                "embedding": [],
                "response_embedding": [],
            },
        )
        return final, state

    final, state = asyncio.run(_run())
    assert final
    assert isinstance(state.get("echo_write_trace"), dict)
    assert state["echo_write_trace"]
    assert state.get("echo_write_allowed") is False
    assert state.get("echo_write_deny_reason") == "orchestrator_hint_skip"
    assert state.get("echo_write_decision_stage") == "anchor_foresight"


def test_p82_conflict_repair_no_duplicate_soft():
    from PersonalityModule.conflict_repair import ConflictRepair

    repair = ConflictRepair()
    result = repair.assess_and_repair(
        "我冇記錯，係你自己亂講，唔好冤枉我。",
        user_input="你記錯咗我講過嘅嘢",
    )
    soft = "我可能講得唔夠清楚，我想誠實對齊返。"
    assert result.text.count(soft) <= 1
    assert "我冇記錯" not in result.text
    assert "係你自己亂講" not in result.text
    assert "唔好冤枉我" not in result.text


def test_p82_conflict_scrub_inject_residue_and_fantastic_clause():
    from PersonalityModule.conflict_repair import (
        AUTOBIO_REPAIR_PREFIX,
        FANTASTIC_CLAUSE_SOFT,
        ConflictRepair,
    )

    repair = ConflictRepair()
    # 模擬 Heretic 注入後再 repair
    denial = repair.assess_and_repair(
        "我明白，喺度，我冇講錯過，你亂講。",
        user_input="你講錯咗",
    )
    assert "我明白" not in denial.text
    assert not denial.text.rstrip("。").endswith("喺度")
    assert not denial.text.rstrip("。").endswith("明白")
    assert "我冇講錯過" not in denial.text

    auto = repair.assess_and_repair(
        "喺度，我爸爸以前成日帶我去火星玩。",
        user_input="你細個點呀",
    )
    assert "我爸爸" not in auto.text
    assert "火星" not in auto.text
    assert "一段我而家唔敢肯定嘅舊事玩" not in auto.text
    assert FANTASTIC_CLAUSE_SOFT in auto.text
    assert auto.text.startswith(AUTOBIO_REPAIR_PREFIX)
    assert not auto.text.startswith("喺度")


def test_p82_heretic_friend_keywords_are_cantonese():
    from PersonalityModule.heretic_coordinator import HereticCoordinator

    h = HereticCoordinator(config={})
    kws = h.island_mapping["Friend"]["keywords"]
    assert "我們" not in kws
    assert "共鳴" not in kws
    assert "姐妹" not in kws
    assert "在場" not in h.island_mapping["Mother"]["keywords"]
    assert "喺呢度" in h.island_mapping["Mother"]["keywords"]


def test_p82_vocal_fluency_no_comma_ellipsis_spam():
    """
    Source + contract：Vocal 不再把「，」批量改成「，…」。
    （VocalPersonalityLayer 依賴 cantonese_dict→pandas；此環境未必有 pandas，
    故用源碼契約；fixture 裁判 no_pipeline_ellipsis_spam 覆蓋執行路徑。）
    """
    src = (ROOT / "PersonalityModule" / "vocal_personality_layer.py").read_text(
        encoding="utf-8"
    )
    assert "replace(\"，\", \"，…\")" not in src
    assert "replace('，', '，…')" not in src
    assert "text.replace(\"，\", \"…\")" not in src
    assert "text.replace('，', '…')" not in src
    # P8.2 註解必須在場，避免之後又加回 spam
    assert "不再把每個「，」改成「，…」" in src
    # 模擬舊行為：若仍把逗號換成省略號會失敗的對照
    text = "我喺度，你攰就休息吓，我陪住你，唔使即刻講晒。"
    legacy_spam = text.replace("，", "，…")
    assert "，…" in legacy_spam
    assert src.count("，…") <= 2  # 僅允許出現在註解／字面說明，非 bulk rewrite


def test_p82_fixture_suite_passes(tmp_path):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    assert lib.P8_VERSION.startswith("8.3")

    class Args:
        mode = "fixture"
        suite = "all"
        url = ""
        model = ""
        out = str(tmp_path / "p8_2_report.json")

    code = asyncio.run(p8.async_main(Args()))
    assert code == 0
    report = Path(Args.out).read_text(encoding="utf-8")
    assert '"status": "passed"' in report
    assert '"acceptance": "P8.3.1"' in report
    assert "anchor_foresight" in report
    assert "duplicate_soft_repair" not in report or '"ok": false' not in report
