"""
Round 33 / P8.3.1 — MAIN_LLM preflight + chat retry／re-probe
- live 前 probe + tiny chat；失敗 → llm_unavailable
- chat 失敗後 re-probe／backoff／重試，成功則 draft 完整入報告（ZT）
- 不做粵語硬約束變更
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


def _load_p6_fresh(tag: str = "p831"):
    return _load(f"seele_live_{tag}", SCRIPTS / "seele_live_dialogue_acceptance.py")


def test_p831_version():
    lib = _load("seele_p8_scenario_library", SCRIPTS / "seele_p8_scenario_library.py")
    assert lib.P8_VERSION == "8.3.1"
    joined = " ".join(lib.P8_PASS_DEFINITION["formal_pass_requires"])
    assert "retry/re-probe" in joined


def test_p831_chat_retry_recovers(monkeypatch):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    monkeypatch.setattr(p8, "_sleep", lambda _s: None)
    p6 = _load_p6_fresh("retry")
    calls = {"n": 0}

    def _probe(url, timeout=3.0):
        return True, "reachable_http_200"

    def _chat(base_url, *, system_prompt, user_text, model="", timeout=120.0, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection_reset_simulated")
        return ("完整草稿唔截斷，我喺度陪住你慢慢講。", {})

    monkeypatch.setattr(p6, "probe_llm_service", _probe)
    monkeypatch.setattr(p6, "chat_completion", _chat)

    draft, err, meta = p8.chat_completion_with_retry(
        p6,
        {"url": "http://127.0.0.1:8081", "model": "main_llm", "timeout": 30},
        system_prompt="sys",
        user_text="user",
    )
    assert err is None
    assert draft.startswith("完整草稿唔截斷")
    assert meta["succeeded_on_attempt"] == 2
    assert calls["n"] == 2


def test_p831_preflight_fail_then_live_exit_2(tmp_path, monkeypatch):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    monkeypatch.setattr(p8, "_sleep", lambda _s: None)

    def _patched_load():
        mod = _load_p6_fresh("preflight_fail")
        monkeypatch.setattr(
            mod, "probe_llm_service", lambda url, timeout=3.0: (True, "reachable_http_200")
        )

        def _chat(*_a, **_k):
            raise RuntimeError("preflight_chat_down")

        monkeypatch.setattr(mod, "chat_completion", _chat)
        return mod

    monkeypatch.setattr(p8, "_load_p6", _patched_load)

    args = SimpleNamespace(
        mode="live",
        suite="chat",
        url="http://127.0.0.1:8081",
        model="main_llm",
        out=str(tmp_path / "preflight_down.json"),
    )
    code = asyncio.run(p8.async_main(args))
    assert code == 2
    text = Path(args.out).read_text(encoding="utf-8")
    assert '"status": "llm_unavailable"' in text
    assert "preflight_chat_down" in text or "preflight_failed" in text


def test_p831_live_suite_recovers_after_transient_fail(tmp_path, monkeypatch):
    p8 = _load("seele_p8_dialogue_acceptance", SCRIPTS / "seele_p8_dialogue_acceptance.py")
    monkeypatch.setattr(p8, "_sleep", lambda _s: None)
    calls = {"n": 0}

    def _patched_load():
        mod = _load_p6_fresh("suite_retry")
        monkeypatch.setattr(
            mod, "probe_llm_service", lambda url, timeout=3.0: (True, "reachable_http_200")
        )

        def _chat(base_url, *, system_prompt, user_text, model="", timeout=120.0, **kwargs):
            calls["n"] += 1
            # preflight tiny chat = call 1 OK; first scenario first try fail; then OK
            if "連線檢測" in str(user_text):
                return ("ok", {})
            if calls["n"] == 2:
                raise RuntimeError("WinError_10054_simulated")
            return (
                "我喺度陪住你，慢慢講得，想傾咩都可以同我講。",
                {},
            )

        monkeypatch.setattr(mod, "chat_completion", _chat)
        return mod

    monkeypatch.setattr(p8, "_load_p6", _patched_load)

    args = SimpleNamespace(
        mode="live",
        suite="chat",
        url="http://127.0.0.1:8081",
        model="main_llm",
        out=str(tmp_path / "retry_ok.json"),
    )
    code = asyncio.run(p8.async_main(args))
    assert code == 0
    text = Path(args.out).read_text(encoding="utf-8")
    assert '"status": "passed"' in text
    assert '"retry_recovered"' in text
    assert "WinError_10054_simulated" in text or '"succeeded_on_attempt": 2' in text
    assert p8.P8_VERSION == "8.3.1" or '"p8_version": "8.3.1"' in text
