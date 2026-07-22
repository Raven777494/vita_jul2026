"""
Round 32 / P8.3.0 — live MAIN_LLM 接線
- --mode live：probe 失敗 → llm_unavailable exit 2
- --mode live：probe 成功 → chat_completion → anchor（mock）
- conflict 仍用 bad_draft fixture
- fixture 回歸仍綠
- Zero-Truncation：報告存完整 draft／final 字元數
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_p6_fresh():
    return _load("seele_live_p830_fresh", SCRIPTS / "seele_live_dialogue_acceptance.py")


def test_p830_live_prompt_ctx_budget_keeps_soul_full():
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    soul_body = "窗外小販與麻雀聲，天花扇慢慢轉。" + ("安" * 50)
    guidance = {
        "system_prompt": "X" * 5000,
        "intensity": "low",
        "soul_memory": {"memory_id": "memory_01", "content": soul_body},
        "soul_memory_id": "memory_01",
    }
    live, meta = p8.build_live_generation_prompt(guidance)
    assert meta["prompt_mode"] == "ctx_budget"
    assert meta["soul_content_full_in_live"] is True
    assert soul_body in live
    assert meta["full_prompt_chars"] == 5000


def test_p830_version_and_pass_definition():
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    assert lib.P8_VERSION.startswith("8.3")
    assert "P8.3 live" in " ".join(lib.P8_PASS_DEFINITION["formal_pass_requires"])


def test_p830_live_unavailable_exit_2(tmp_path, monkeypatch):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    monkeypatch.setattr(p8, "_sleep", lambda _s: None)

    def _patched_load():
        mod = _load_p6_fresh()
        monkeypatch.setattr(
            mod, "probe_llm_service", lambda url, timeout=3.0: (False, "connection_refused")
        )
        return mod

    monkeypatch.setattr(p8, "_load_p6", _patched_load)

    args = SimpleNamespace(
        mode="live",
        suite="chat",
        url="http://127.0.0.1:8081",
        model="main_llm",
        out=str(tmp_path / "live_down.json"),
    )
    code = asyncio.run(p8.async_main(args))
    assert code == 2
    report = Path(args.out).read_text(encoding="utf-8")
    assert '"status": "llm_unavailable"' in report
    assert '"acceptance": "P8.3.1"' in report
    assert "preflight" in report


def test_p830_live_uses_chat_completion(tmp_path, monkeypatch):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    monkeypatch.setattr(p8, "_sleep", lambda _s: None)

    def _patched_load():
        mod = _load_p6_fresh()
        monkeypatch.setattr(
            mod, "probe_llm_service", lambda url, timeout=3.0: (True, "reachable_http_200")
        )

        def _fake_chat(
            base_url,
            *,
            system_prompt,
            user_text,
            model="",
            timeout=120.0,
            **kwargs,
        ):
            assert system_prompt
            assert user_text
            # 足夠長以過 min_chars；全文入報告（ZT）
            return (
                "我喺度陪住你，慢慢講得，想傾咩都可以同我講。",
                {"choices": [{"message": {"content": "x"}}]},
            )

        monkeypatch.setattr(mod, "chat_completion", _fake_chat)
        return mod

    monkeypatch.setattr(p8, "_load_p6", _patched_load)

    args = SimpleNamespace(
        mode="live",
        suite="chat",
        url="http://127.0.0.1:8081",
        model="main_llm",
        out=str(tmp_path / "live_ok.json"),
    )
    code = asyncio.run(p8.async_main(args))
    assert code == 0
    text = Path(args.out).read_text(encoding="utf-8")
    assert '"status": "passed"' in text
    assert '"draft_source": "live_llm"' in text
    assert '"used_live_llm": true' in text
    assert "live_llm_dialogue" in text
    assert "我喺度陪住你，慢慢講得，想傾咩都可以同我講。" in text
    assert '"acceptance": "P8.3.1"' in text
    assert "preflight" in text


def test_p830_fixture_still_passes(tmp_path):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    args = SimpleNamespace(
        mode="fixture",
        suite="all",
        url="",
        model="",
        out=str(tmp_path / "fixture.json"),
    )
    code = asyncio.run(p8.async_main(args))
    assert code == 0
    text = Path(args.out).read_text(encoding="utf-8")
    assert '"status": "passed"' in text
    assert '"acceptance": "P8.3.1"' in text
    assert '"draft_source": "fixture"' in text
