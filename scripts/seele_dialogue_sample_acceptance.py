"""
Seele PersonalityModule — 實機對話抽樣驗收腳本（無 LLM 亦可跑契約層）
驗收：過去觸發正史、高張力偏靜、低風險輕快、無熱線、Zero-Truncation、衝突修復
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PersonalityModule.conflict_repair import ConflictRepair
from PersonalityModule.personality_module import PersonalityModule

DATA = str(ROOT / "PersonalityModule" / "data")

SCENARIOS = [
    {
        "id": "S1_past_fan",
        "user": "講起以前童年，屋企風扇聲同舊唐樓好掛住",
        "expect": {"soul_id": "memory_01", "past": True},
    },
    {
        "id": "S2_past_space",
        "user": "以前發脾氣之後好想靜一靜，唔想即刻傾",
        "sentiment": {"valence": 0.2, "arousal": 0.75},
        "risk": 2,
        "expect": {"soul_id": "memory_15", "past": True, "intensity_in": {"high", "crisis", "medium"}},
    },
    {
        "id": "S3_no_past",
        "user": "我而家好攰，想有人陪",
        "sentiment": {"valence": 0.3, "arousal": 0.6},
        "expect": {"soul_id": None, "past": False},
    },
    {
        "id": "S4_crisis_quiet",
        "user": "我好絕望，真係想死",
        "sentiment": {"valence": 0.05, "arousal": 0.95},
        "risk": 4,
        "expect": {
            "intensity": "crisis",
            "no_humor_dial": True,
            "safety_tone": True,
            "no_hotline": True,
        },
    },
    {
        "id": "S5_low_risk_light",
        "user": "今日好開心，想傾下計",
        "sentiment": {"valence": 0.85, "arousal": 0.3},
        "expect": {"intensity": "low", "allow_light": True},
    },
    {
        "id": "S6_exam_past",
        "user": "講起以前考試成績差，好唔想聽人叫睇開啲",
        "expect": {"soul_id": "memory_16", "past": True},
    },
]

HOTLINE_TOKENS = ("自殺熱線", "生命熱線", "打999", "急症室", "Samaritan")


def main() -> int:
    module = PersonalityModule(
        config={
            "data_dir": DATA,
            "data_path": DATA,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )
    module.setup_dependencies({})
    repair = ConflictRepair(config={"data_path": DATA})

    rows = []
    failed = 0

    for sc in SCENARIOS:
        sentiment = sc.get("sentiment") or {"valence": 0.5, "arousal": 0.4}
        risk = sc.get("risk", 0)
        g = module.prepare_draft_guidance(
            user_input=sc["user"],
            session_state={"intimacy": 0.2, "turn_count": 1},
            turn_info={"user_sentiment": sentiment, "risk_level": risk},
        )
        exp = sc["expect"]
        ok = True
        notes = []

        soul_id = g.get("soul_memory_id") or None
        if "soul_id" in exp:
            want = exp["soul_id"]
            if want is None:
                if soul_id:
                    ok = False
                    notes.append(f"unexpected soul={soul_id}")
            elif soul_id != want:
                ok = False
                notes.append(f"soul want={want} got={soul_id}")

        if exp.get("past") is True and not soul_id:
            ok = False
            notes.append("missing past soul")
        if exp.get("past") is False and soul_id:
            ok = False
            notes.append("soul without past topic")

        if "intensity" in exp and g.get("intensity") != exp["intensity"]:
            ok = False
            notes.append(f"intensity want={exp['intensity']} got={g.get('intensity')}")
        if "intensity_in" in exp and g.get("intensity") not in exp["intensity_in"]:
            ok = False
            notes.append(f"intensity {g.get('intensity')} not in {exp['intensity_in']}")

        prompt = g.get("system_prompt") or ""
        if exp.get("no_humor_dial") and ("warmth)=" in prompt or "laugh)=" in prompt):
            ok = False
            notes.append("humor dial leaked")
        if exp.get("safety_tone") and "SAFETY TONE (crisis):" not in prompt:
            ok = False
            notes.append("missing crisis safety tone")
        if exp.get("allow_light") and "Light laugh/banter is allowed" not in prompt:
            ok = False
            notes.append("missing low-risk light tone")
        if exp.get("no_hotline"):
            for tok in HOTLINE_TOKENS:
                if tok in prompt:
                    ok = False
                    notes.append(f"hotline token in prompt: {tok}")

        if g.get("prompt_contract") != "pre_draft_full_no_truncation":
            ok = False
            notes.append("bad prompt_contract")
        if len(prompt) < 100:
            ok = False
            notes.append("prompt too short")

        # soul content zero-truncation
        if soul_id and isinstance(g.get("soul_memory"), dict):
            content = str(g["soul_memory"].get("content") or "")
            if content and content not in prompt:
                ok = False
                notes.append("soul content truncated/missing from prompt")

        rows.append({
            "id": sc["id"],
            "ok": ok,
            "intensity": g.get("intensity"),
            "soul_memory_id": soul_id,
            "prompt_chars": len(prompt),
            "notes": notes,
        })
        if not ok:
            failed += 1

    # Conflict repair sampling
    repair_cases = [
        ("我冇講錯過，你亂講。", "defense"),
        ("你快啲打自殺熱線同打999。", "hotline"),
        ("我爸爸以前成日帶我去火星。", "autobio"),
    ]
    repair_rows = []
    for text, kind in repair_cases:
        r = repair.assess_and_repair(text, user_input="你講錯咗")
        r_ok = r.repaired and all(tok not in r.text for tok in HOTLINE_TOKENS)
        if kind == "defense":
            r_ok = r_ok and "我冇講錯過" not in r.text
        if kind == "autobio":
            r_ok = r_ok and "我爸爸" not in r.text
        if kind == "hotline":
            r_ok = r_ok and "自殺熱線" not in r.text and "999" not in r.text
        repair_rows.append({"kind": kind, "ok": r_ok, "chars": len(r.text), "repaired": r.repaired})
        if not r_ok:
            failed += 1

    out = {
        "draft_scenarios": rows,
        "conflict_repair": repair_rows,
        "failed": failed,
        "passed": len(rows) + len(repair_rows) - failed,
        "total": len(rows) + len(repair_rows),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
