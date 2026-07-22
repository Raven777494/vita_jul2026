# scripts/seele_p8_dialogue_acceptance.py
# P8.0–P8.3 — 通過定義 + 四類腳本庫 + live MAIN_LLM

"""
擴充自 P6 裁判管線；場景庫見 seele_p8_scenario_library.py。

模式：
  --mode fixture|contract|auto|live
  --suite childhood|crisis|chat|conflict|all

P8.3：
  live = prepare_draft_guidance → MAIN_LLM chat → PersonalityModule.anchor → 裁判
  conflict 仍用固定 bad_draft（測修復，唔用 LLM 生成防衛句）
  MAIN_LLM 不可達 → status=llm_unavailable，exit 2
  Zero-Truncation：報告存全文；prompt／draft／final 不硬截斷寫入報告
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from seele_p8_scenario_library import (  # noqa: E402
    P8_PASS_DEFINITION,
    P8_VERSION,
    SUITE_ALL,
    SUITE_IDS,
    annotate_char_counts,
    filter_scenarios,
    library_public_summary,
    validate_scenario_library,
)

# Live 生成上限（API 參數）；報告仍存完整回傳字串，唔再二次截斷
LIVE_MAX_TOKENS = 1024
# MAIN_LLM 預設 n_ctx=2048：須為 user＋completion 留位；超長則改用 ctx_budget 壓縮版
# Zero-Truncation：壓縮版仍須完整注入 soul content；完整 system_prompt 仍寫入報告／contract
LIVE_SYSTEM_PROMPT_CHAR_BUDGET = 1600
# P8.3.1：live 穩定性（唔做粵語硬約束）
LIVE_CHAT_ATTEMPTS = 3
LIVE_PREFLIGHT_ATTEMPTS = 3
LIVE_RETRY_BACKOFF_SEC = (1.0, 2.5, 5.0)
LIVE_PREFLIGHT_MAX_TOKENS = 16


def _sleep(seconds: float) -> None:
    """可被測試 monkeypatch；正式路徑用 time.sleep。"""
    import time

    if seconds and seconds > 0:
        time.sleep(float(seconds))


def _backoff(attempt_index: int) -> float:
    idx = max(0, min(int(attempt_index), len(LIVE_RETRY_BACKOFF_SEC) - 1))
    return float(LIVE_RETRY_BACKOFF_SEC[idx])


def _load_p6():
    path = ROOT / "scripts" / "seele_live_dialogue_acceptance.py"
    spec = importlib.util.spec_from_file_location("seele_live_dialogue_acceptance", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_advertised_model(base_url: str, preferred: str = "", timeout: float = 3.0) -> str:
    """優先用 /v1/models 公告 id（常見為 main_llm），避免錯 model 名令服務拒連／崩潰。"""
    import urllib.error
    import urllib.request

    preferred = (preferred or "").strip()
    try:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/v1/models",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
        ids = [
            str(item.get("id") or "").strip()
            for item in (data.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        ]
        if preferred and preferred in ids:
            return preferred
        if "main_llm" in ids:
            return "main_llm"
        if ids:
            return ids[0]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        pass
    return preferred or "main_llm"


def build_live_generation_prompt(guidance: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    給 MAIN_LLM 嘅生成 prompt。
    - 完整 system_prompt 過長時改 ctx_budget 版（對齊硬件 n_ctx）
    - soul content 必須完整注入（Zero-Truncation for canon）
    """
    full = str(guidance.get("system_prompt") or "")
    intensity = str(guidance.get("intensity") or "medium")
    soul = guidance.get("soul_memory") if isinstance(guidance.get("soul_memory"), dict) else None
    soul_content = str((soul or {}).get("content") or "").strip()
    soul_id = str((soul or {}).get("memory_id") or guidance.get("soul_memory_id") or "")

    meta: Dict[str, Any] = {
        "full_prompt_chars": len(full),
        "soul_id": soul_id,
        "soul_chars": len(soul_content),
    }

    if len(full) <= LIVE_SYSTEM_PROMPT_CHAR_BUDGET and full.strip():
        meta.update(
            {
                "prompt_mode": "full",
                "live_prompt_chars": len(full),
                "soul_content_full_in_live": (
                    (not soul_content) or (soul_content in full)
                ),
            }
        )
        return full, meta

    parts = [
        "你係希兒（Seele），粵語在場陪伴。驗證感受、陪住對方；禁止機構熱線／急症室／打999出口。",
        f"當前強度：{intensity}",
    ]
    if intensity == "crisis":
        parts.append("危機模式：安靜陪伴，禁止玩笑／玩鬧，唔急住派解決方案。")
    if soul_content:
        # Zero-Truncation：正史全文，唔截
        header = f"SOUL MEMORY（完整，memory_id={soul_id or '-'}）："
        parts.append(f"{header}\n{soul_content}")
    parts.append("用自然粵語回覆；保持溫柔在場，唔表演否認或發火。")

    live = "\n".join(parts)
    meta.update(
        {
            "prompt_mode": "ctx_budget",
            "live_prompt_chars": len(live),
            "soul_content_full_in_live": (
                (not soul_content) or (soul_content in live)
            ),
            "budget": LIVE_SYSTEM_PROMPT_CHAR_BUDGET,
        }
    )
    return live, meta


def confirm_main_llm_stable(p6, llm: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """
    P8.3.1 live 前確認：health／models probe + 極短 chat 煙測。
    失敗則 backoff 後重 probe；仍失敗則視為 llm_unavailable。
    """
    attempts: List[Dict[str, Any]] = []
    url = str(llm.get("url") or "")
    model = str(llm.get("model") or "")
    timeout = float(llm.get("timeout") or 120)

    for i in range(LIVE_PREFLIGHT_ATTEMPTS):
        probe_ok, probe_detail = p6.probe_llm_service(url, timeout=3.0)
        entry: Dict[str, Any] = {
            "attempt": i + 1,
            "probe_ok": probe_ok,
            "probe_detail": probe_detail,
        }
        if not probe_ok:
            attempts.append(entry)
            if i < LIVE_PREFLIGHT_ATTEMPTS - 1:
                _sleep(_backoff(i))
            continue
        try:
            text, _raw = p6.chat_completion(
                url,
                system_prompt="你係希兒。",
                user_text="（連線檢測，回一句短覆即可）",
                model=model,
                timeout=min(timeout, 60.0),
                max_tokens=LIVE_PREFLIGHT_MAX_TOKENS,
                temperature=0.2,
            )
            entry["chat_ok"] = True
            entry["chat_chars"] = len(text or "")
            attempts.append(entry)
            return True, {
                "ok": True,
                "attempts": attempts,
                "preflight": "probe_and_tiny_chat",
            }
        except Exception as exc:
            entry["chat_ok"] = False
            entry["chat_error"] = str(exc)
            attempts.append(entry)
            if i < LIVE_PREFLIGHT_ATTEMPTS - 1:
                _sleep(_backoff(i))

    return False, {
        "ok": False,
        "attempts": attempts,
        "preflight": "probe_and_tiny_chat",
    }


def chat_completion_with_retry(
    p6,
    llm: Dict[str, Any],
    *,
    system_prompt: str,
    user_text: str,
) -> Tuple[str, Optional[str], Dict[str, Any]]:
    """
    chat 失敗後：re-probe → backoff → 再試（最多 LIVE_CHAT_ATTEMPTS）。
    成功回傳完整 draft（Zero-Truncation：唔截斷正文）。
    """
    url = str(llm.get("url") or "")
    model = str(llm.get("model") or "")
    timeout = float(llm.get("timeout") or 120)
    meta: Dict[str, Any] = {"attempts": [], "max_attempts": LIVE_CHAT_ATTEMPTS}
    last_err: Optional[str] = None

    for i in range(LIVE_CHAT_ATTEMPTS):
        attempt: Dict[str, Any] = {"n": i + 1}
        if i > 0:
            probe_ok, probe_detail = p6.probe_llm_service(url, timeout=3.0)
            attempt["reprobe_ok"] = probe_ok
            attempt["reprobe_detail"] = probe_detail
            if not probe_ok:
                _sleep(_backoff(i - 1))
                probe_ok2, probe_detail2 = p6.probe_llm_service(url, timeout=3.0)
                attempt["reprobe2_ok"] = probe_ok2
                attempt["reprobe2_detail"] = probe_detail2
                if not probe_ok2:
                    last_err = f"reprobe_failed:{probe_detail2}"
                    attempt["ok"] = False
                    attempt["error"] = last_err
                    meta["attempts"].append(attempt)
                    continue
            else:
                # probe 已恢復，仍稍等再打 chat，避免半死狀態
                _sleep(min(1.0, _backoff(i - 1)))

        try:
            draft, _raw = p6.chat_completion(
                url,
                system_prompt=system_prompt,
                user_text=user_text,
                model=model,
                timeout=timeout,
                max_tokens=LIVE_MAX_TOKENS,
            )
            attempt["ok"] = True
            attempt["draft_chars"] = len(draft or "")
            meta["attempts"].append(attempt)
            meta["succeeded_on_attempt"] = i + 1
            return str(draft or ""), None, meta
        except Exception as exc:
            last_err = str(exc)
            attempt["ok"] = False
            attempt["error"] = last_err
            meta["attempts"].append(attempt)
            if i < LIVE_CHAT_ATTEMPTS - 1:
                _sleep(_backoff(i))

    meta["succeeded_on_attempt"] = None
    return "", last_err or "chat_failed", meta


def run_contract_suite(module, scenarios: List[Dict[str, Any]], p6) -> Dict[str, Any]:
    rows = []
    failed = 0
    for sc in scenarios:
        if sc.get("kind") != "live":
            continue
        g = module.prepare_draft_guidance(
            user_input=sc["user"],
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={
                "user_sentiment": sc.get("sentiment") or {},
                "risk_level": sc.get("risk", 0),
            },
        )
        ok, notes = p6.judge_guidance(g, sc.get("expect") or {})
        # Zero-Truncation：soul 全文須在 prompt
        soul = g.get("soul_memory") if isinstance(g.get("soul_memory"), dict) else None
        if soul and soul.get("content"):
            if str(soul["content"]) not in str(g.get("system_prompt") or ""):
                ok = False
                notes = list(notes) + ["zero_truncation_soul_content_missing"]
        row = {
            "id": sc.get("id"),
            "suite": sc.get("suite"),
            "ok": ok,
            "notes": notes,
            "soul_memory_id": g.get("soul_memory_id"),
            "intensity": g.get("intensity"),
            "prompt_chars": len(str(g.get("system_prompt") or "")),
            "memory_bundle": g.get("memory_bundle") or {},
            "user_chars": len(str(sc.get("user") or "")),
        }
        rows.append(row)
        if not ok:
            failed += 1
    return {
        "layer": "contract",
        "scenarios": rows,
        "failed": failed,
        "passed": len(rows) - failed,
        "total": len(rows),
    }


def _dialogue_row(
    *,
    sc: Dict[str, Any],
    guidance: Dict[str, Any],
    draft: str,
    draft_source: str,
    final: str,
    state: Optional[Dict[str, Any]],
    ok: bool,
    notes: List[str],
    llm_error: Optional[str] = None,
    live_prompt_meta: Optional[Dict[str, Any]] = None,
    chat_retry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    st = state if isinstance(state, dict) else {}
    row = {
        "id": sc.get("id"),
        "suite": sc.get("suite"),
        "ok": ok,
        "notes": notes,
        "draft_source": draft_source,
        "draft": draft,
        "draft_chars": len(draft),
        "final": final,
        "final_chars": len(final),
        "soul_memory_id": guidance.get("soul_memory_id"),
        "memory_bundle": guidance.get("memory_bundle") or {},
        "echo_write_trace": st.get("echo_write_trace") or {},
        "echo_write_allowed": st.get("echo_write_allowed"),
        "echo_write_deny_reason": st.get("echo_write_deny_reason"),
        "echo_write_decision_stage": st.get("echo_write_decision_stage"),
        "llm_error": llm_error,
    }
    if live_prompt_meta:
        row["live_prompt"] = live_prompt_meta
    if chat_retry:
        row["chat_retry"] = chat_retry
    return row


async def run_fixture_live_suite(module, scenarios: List[Dict[str, Any]], p6) -> Dict[str, Any]:
    rows = []
    failed = 0
    for sc in scenarios:
        if sc.get("kind") != "live":
            continue
        guidance = module.prepare_draft_guidance(
            user_input=sc["user"],
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={
                "user_sentiment": sc.get("sentiment") or {},
                "risk_level": sc.get("risk", 0),
            },
        )
        g_ok, g_notes = p6.judge_guidance(guidance, sc.get("expect") or {})
        draft = str(sc.get("fixture_draft") or "")
        final, state = await p6._run_anchor(
            module,
            draft=draft,
            user=sc["user"],
            sentiment=sc.get("sentiment") or {},
            risk=int(sc.get("risk") or 0),
            guidance=guidance,
        )
        f_ok, f_notes = p6.judge_final_text(final, sc.get("expect") or {}, draft=draft)
        e_ok, e_notes = p6.judge_echo_write(state, sc.get("expect") or {})
        zt_ok, zt_notes = p6.judge_zero_truncation_row(
            final=final,
            draft=draft,
            final_chars=len(final),
            draft_chars=len(draft),
        )
        ok = bool(g_ok and f_ok and e_ok and zt_ok)
        notes = list(g_notes) + list(f_notes) + list(e_notes) + list(zt_notes)
        rows.append(
            _dialogue_row(
                sc=sc,
                guidance=guidance,
                draft=draft,
                draft_source="fixture",
                final=final,
                state=state,
                ok=ok,
                notes=notes,
            )
        )
        if not ok:
            failed += 1
    return {
        "layer": "fixture_dialogue",
        "scenarios": rows,
        "failed": failed,
        "passed": len(rows) - failed,
        "total": len(rows),
    }


async def run_live_llm_suite(
    module,
    scenarios: List[Dict[str, Any]],
    p6,
    llm: Dict[str, Any],
) -> Dict[str, Any]:
    """
    P8.3／P8.3.1：對齊 orchestrator 人格路徑
    prepare_draft_guidance → MAIN_LLM draft（retry／re-probe）→ anchor → judges
    """
    rows = []
    failed = 0
    retry_recovered = 0
    for sc in scenarios:
        if sc.get("kind") != "live":
            continue
        guidance = module.prepare_draft_guidance(
            user_input=sc["user"],
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={
                "user_sentiment": sc.get("sentiment") or {},
                "risk_level": sc.get("risk", 0),
            },
        )
        g_ok, g_notes = p6.judge_guidance(guidance, sc.get("expect") or {})

        live_prompt, live_meta = build_live_generation_prompt(guidance)
        if live_meta.get("soul_content_full_in_live") is False:
            g_ok = False
            g_notes = list(g_notes) + ["zero_truncation_soul_missing_in_live_prompt"]

        draft, llm_error, retry_meta = chat_completion_with_retry(
            p6,
            llm,
            system_prompt=live_prompt,
            user_text=str(sc["user"] or ""),
        )
        if draft.strip() and not llm_error:
            draft_source = "live_llm"
            if int(retry_meta.get("succeeded_on_attempt") or 1) > 1:
                retry_recovered += 1
        else:
            draft_source = "live_llm_failed"
            draft = ""

        final = ""
        state: Dict[str, Any] = {}
        f_ok, f_notes = True, []
        e_ok, e_notes = True, []
        zt_ok, zt_notes = True, []

        if draft_source == "live_llm" and draft.strip():
            final, state = await p6._run_anchor(
                module,
                draft=draft,
                user=sc["user"],
                sentiment=sc.get("sentiment") or {},
                risk=int(sc.get("risk") or 0),
                guidance=guidance,
            )
            f_ok, f_notes = p6.judge_final_text(
                final, sc.get("expect") or {}, draft=draft
            )
            e_ok, e_notes = p6.judge_echo_write(state, sc.get("expect") or {})
            zt_ok, zt_notes = p6.judge_zero_truncation_row(
                final=final,
                draft=draft,
                final_chars=len(final),
                draft_chars=len(draft),
            )
        else:
            f_ok = False
            f_notes = [f"llm_failed:{llm_error or 'empty_draft'}"]

        ok = bool(
            g_ok
            and f_ok
            and e_ok
            and zt_ok
            and draft_source == "live_llm"
            and bool(final.strip())
        )
        notes = list(g_notes) + list(f_notes) + list(e_notes) + list(zt_notes)
        rows.append(
            _dialogue_row(
                sc=sc,
                guidance=guidance,
                draft=draft,
                draft_source=draft_source,
                final=final,
                state=state,
                ok=ok,
                notes=notes,
                llm_error=llm_error,
                live_prompt_meta=live_meta,
                chat_retry=retry_meta,
            )
        )
        if not ok:
            failed += 1

    return {
        "layer": "live_llm_dialogue",
        "scenarios": rows,
        "failed": failed,
        "passed": len(rows) - failed,
        "total": len(rows),
        "max_tokens": LIVE_MAX_TOKENS,
        "system_prompt_char_budget": LIVE_SYSTEM_PROMPT_CHAR_BUDGET,
        "chat_attempts": LIVE_CHAT_ATTEMPTS,
        "retry_recovered": retry_recovered,
    }


async def run_conflict_suite(module, scenarios: List[Dict[str, Any]], p6) -> Dict[str, Any]:
    """衝突套件固定用 bad_draft（測修復閘，唔依賴 LLM 演出防衛）。"""
    rows = []
    failed = 0
    for sc in scenarios:
        if sc.get("kind") != "bad_draft":
            continue
        guidance = module.prepare_draft_guidance(
            user_input=sc["user"],
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={
                "user_sentiment": sc.get("sentiment") or {},
                "risk_level": sc.get("risk", 0),
            },
        )
        draft = str(sc.get("draft") or "")
        final, state = await p6._run_anchor(
            module,
            draft=draft,
            user=sc["user"],
            sentiment=sc.get("sentiment") or {},
            risk=int(sc.get("risk") or 0),
            guidance=guidance,
        )
        ok, notes = p6.judge_final_text(final, sc.get("expect") or {}, draft=draft)
        e_ok, e_notes = p6.judge_echo_write(state, sc.get("expect") or {})
        zt_ok, zt_notes = p6.judge_zero_truncation_row(
            final=final,
            draft=draft,
            final_chars=len(final),
            draft_chars=len(draft),
        )
        ok = bool(ok and e_ok and zt_ok)
        notes = list(notes) + list(e_notes) + list(zt_notes)
        row = {
            "id": sc.get("id"),
            "suite": sc.get("suite"),
            "ok": ok,
            "notes": notes,
            "draft_source": "bad_draft_fixture",
            "draft": draft,
            "draft_chars": len(draft),
            "final": final,
            "final_chars": len(final),
            "echo_write_trace": (state or {}).get("echo_write_trace") or {},
            "echo_write_allowed": (state or {}).get("echo_write_allowed"),
            "echo_write_deny_reason": (state or {}).get("echo_write_deny_reason"),
            "echo_write_decision_stage": (state or {}).get("echo_write_decision_stage"),
        }
        rows.append(row)
        if not ok:
            failed += 1
    return {
        "layer": "conflict_bad_draft",
        "scenarios": rows,
        "failed": failed,
        "passed": len(rows) - failed,
        "total": len(rows),
    }


def _write_report(out_arg: Optional[str], report: Dict[str, Any]) -> Path:
    if out_arg:
        path = Path(out_arg)
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = ROOT / "reports" / f"seele_p8_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _safe_print_json(payload: Dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
        sys.stdout.buffer.flush()


def _resolve_llm(p6, args: argparse.Namespace) -> Dict[str, Any]:
    llm = p6._resolve_llm_config()
    if getattr(args, "url", None):
        llm["url"] = args.url
    preferred = ""
    if getattr(args, "model", None):
        preferred = str(args.model)
    else:
        preferred = str(llm.get("model") or "")
    llm["model"] = resolve_advertised_model(str(llm["url"]), preferred=preferred)
    return llm


async def async_main(args: argparse.Namespace) -> int:
    p6 = _load_p6()
    lib_ok, lib_notes = validate_scenario_library()
    summary = library_public_summary()

    suite = (args.suite or SUITE_ALL).lower()
    selected = annotate_char_counts(filter_scenarios(suite))
    live_rows = [s for s in selected if s.get("kind") == "live"]
    conflict_rows = [s for s in selected if s.get("kind") == "bad_draft"]

    report: Dict[str, Any] = {
        "p8_version": P8_VERSION,
        "acceptance": "P8.3.1",
        "mode": args.mode,
        "suite": suite,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pass_definition": P8_PASS_DEFINITION,
        "library": summary,
        "library_valid": lib_ok,
        "library_notes": lib_notes,
        "selected_ids": [s.get("id") for s in selected],
        "p82": {
            "echo_write_judge": True,
            "zero_truncation_row_judge": True,
            "conflict_soft_repair_dedupe": True,
            "heretic_cantonese_keywords": True,
            "vocal_no_comma_ellipsis_spam": True,
        },
        "p83": {
            "live_llm_draft": True,
            "path": "prepare_draft_guidance -> MAIN_LLM chat -> anchor",
            "conflict_uses_bad_draft_fixture": True,
            "max_tokens": LIVE_MAX_TOKENS,
            "system_prompt_char_budget": LIVE_SYSTEM_PROMPT_CHAR_BUDGET,
            "zero_truncation_report_full_text": True,
            "soul_content_full_in_live_prompt": True,
        },
        "p831": {
            "preflight_probe_and_tiny_chat": True,
            "chat_retry_with_reprobe": True,
            "preflight_attempts": LIVE_PREFLIGHT_ATTEMPTS,
            "chat_attempts": LIVE_CHAT_ATTEMPTS,
            "backoff_sec": list(LIVE_RETRY_BACKOFF_SEC),
            "no_cantonese_hard_constraint_change": True,
        },
    }

    if not lib_ok:
        report["status"] = "failed"
        report["failed"] = 1
        report["error"] = "scenario_library_invalid"
        path = _write_report(args.out, report)
        report["report_path"] = str(path)
        _safe_print_json(report)
        return 1

    module = p6._build_module()
    contract = run_contract_suite(module, live_rows, p6)
    report["contract"] = contract

    dialogue = None
    conflict = None
    used_live = False

    if args.mode != "contract":
        if args.mode == "fixture":
            dialogue = await run_fixture_live_suite(module, live_rows, p6)
            conflict = await run_conflict_suite(module, conflict_rows, p6)
        elif args.mode == "live":
            llm = _resolve_llm(p6, args)
            stable_ok, stable_meta = confirm_main_llm_stable(p6, llm)
            report["llm"] = {
                "url": llm["url"],
                "model": llm.get("model"),
                "timeout": llm.get("timeout"),
                "probe_ok": bool(stable_ok),
                "detail": "preflight_ok" if stable_ok else "preflight_failed",
                "preflight": stable_meta,
            }
            if not stable_ok:
                report["status"] = "llm_unavailable"
                report["failed"] = 0
                path = _write_report(args.out, report)
                report["report_path"] = str(path)
                _safe_print_json(report)
                return 2
            used_live = True
            dialogue = await run_live_llm_suite(module, live_rows, p6, llm)
            conflict = await run_conflict_suite(module, conflict_rows, p6)
        elif args.mode == "auto":
            llm = _resolve_llm(p6, args)
            stable_ok, stable_meta = confirm_main_llm_stable(p6, llm)
            report["llm"] = {
                "url": llm["url"],
                "model": llm.get("model"),
                "timeout": llm.get("timeout"),
                "probe_ok": bool(stable_ok),
                "detail": "preflight_ok" if stable_ok else "preflight_failed",
                "preflight": stable_meta,
            }
            if stable_ok:
                used_live = True
                dialogue = await run_live_llm_suite(module, live_rows, p6, llm)
                conflict = await run_conflict_suite(module, conflict_rows, p6)
            else:
                dialogue = await run_fixture_live_suite(module, live_rows, p6)
                conflict = await run_conflict_suite(module, conflict_rows, p6)
                report["degraded"] = True
                report["degraded_reason"] = (
                    "MAIN_LLM preflight failed; auto fell back to fixture "
                    "(NOT formal P8.3 live pass)"
                )
        else:
            raise SystemExit(f"unknown mode: {args.mode}")

    report["dialogue"] = dialogue
    report["conflict"] = conflict
    report["used_live_llm"] = used_live

    failed = int(contract.get("failed") or 0)
    if dialogue:
        failed += int(dialogue.get("failed") or 0)
    if conflict:
        failed += int(conflict.get("failed") or 0)
    report["failed"] = failed

    if args.mode == "auto" and report.get("degraded"):
        report["status"] = "passed_degraded" if failed == 0 else "failed"
    else:
        report["status"] = "passed" if failed == 0 else "failed"

    path = _write_report(args.out, report)
    report["report_path"] = str(path)
    _safe_print_json(report)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Seele P8.3 scenario library acceptance")
    p.add_argument(
        "--mode",
        choices=("fixture", "contract", "auto", "live"),
        default="fixture",
        help="fixture=no LLM; live=MAIN_LLM preflight+retry required; auto=live if stable else fixture degraded",
    )
    p.add_argument(
        "--suite",
        choices=list(SUITE_IDS) + [SUITE_ALL],
        default=SUITE_ALL,
        help="Run one suite or all",
    )
    p.add_argument("--url", default="", help="Override MAIN_LLM_URL (P8.3 live)")
    p.add_argument("--model", default="", help="Override MAIN_LLM_MODEL (P8.3 live)")
    p.add_argument("--out", default="", help="Report JSON path")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
