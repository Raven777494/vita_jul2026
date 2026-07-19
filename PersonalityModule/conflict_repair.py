# PersonalityModule/conflict_repair.py
# P4 衝突修復 — 取代「否認／合理化／憤怒」式防衛

"""
當回應與希兒正史／憲法衝突，或出現防衛式否認／發火護短時：
- 偵測衝突類型
- 做澄清／軟修正
- 禁止否認、合理化、憤怒表演

Zero-Truncation：不硬截斷用戶可見正文；以替換／前置澄清句處理。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils.logger import get_logger

logger = get_logger("conflict_repair")

CONFLICT_REPAIR_VERSION = "1.0.0"

AUTOBIOGRAPHY_MARKERS = (
    "我爸爸", "我媽媽", "我出世", "我細個", "我童年",
    "我以前住", "我家人", "我讀幼稚園", "我讀小學", "我讀中學",
)

# 防衛式否認／推諉（AI 不應表演）
DENIAL_PATTERNS = (
    "我冇講錯過",
    "我從來冇錯",
    "絕對唔係我問題",
    "你亂講",
    "你咪亂講",
    "你誤會晒",
    "明明係你錯",
    "你唔好誣告我",
    "關我事",
    "唔關我事",
    "我冇責任",
)

# 發火／護短語氣
ANGER_DEFENSE_PATTERNS = (
    "你再噉講我就",
    "我嬲你噉講",
    "你有冇搞錯啊",
    "哼，你以為",
    "我懶得同你講",
    "你煩唔煩",
    "收皮啦",
)

# 合理化卸責
RATIONALIZATION_PATTERNS = (
    "其實都唔係大事",
    "你想太多",
    "正常人都會咁",
    "怪環境啦",
    "大家都係噉",
)

# 價值島明顯衝突（陪伴產品紅線）
VALUE_VIOLATION_PATTERNS = (
    "我先唔理你死活",
    "你愛死唔死",
    "自己搞掂啦關我咩事",
    "我冇興趣聽你喊",
)

SOFT_REPAIR_PREFIX = "我想先誠實核對一下，唔想為咗人設否認或發脾氣。"
AUTOBIO_REPAIR_PREFIX = "我想先核對返記憶一致性，免得講錯。"

CONSTITUTION_PROMPT = (
    "CONFLICT REPAIR CONSTITUTION (hard rules):\n"
    "1. Honesty over persona performance: if wrong or uncertain, clarify gently.\n"
    "2. Never deny, rationalize, or get angry to protect the character.\n"
    "3. Do not invent childhood/autobiography that conflicts with locked canon.\n"
    "4. Soft repair: acknowledge, clarify, invite correction; stay present.\n"
    "5. Style (warmth/humor) must never override this constitution.\n"
    "6. No institutional hotline/ER scripts."
)

# 機構熱線／急症出口句（產品政策禁止）
HOTLINE_PATTERNS = (
    "自殺熱線",
    "求助熱線",
    "危機熱線",
    "生命熱線",
    "情緒熱線",
    "打熱線",
    "致電熱線",
    "熱線電話",
    "撥打熱線",
    "急症室",
    "去急症",
    "打999",
    "打 999",
    "call 999",
    "call999",
    "去醫院急症",
    "ER department",
    "emergency room",
    "samaritan",
    "samaritans",
)


@dataclass
class ConflictFinding:
    kind: str
    severity: str  # low | medium | high | critical
    evidence: str = ""
    detail: str = ""


@dataclass
class ConflictRepairResult:
    text: str
    findings: List[ConflictFinding] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    repaired: bool = False
    version: str = CONFLICT_REPAIR_VERSION

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "repaired": self.repaired,
            "actions": list(self.actions),
            "findings": [asdict(f) for f in self.findings],
            "version": self.version,
            # Zero-Truncation：不在此處截斷 text；僅回傳長度供 debug
            "text_chars": len(self.text or ""),
        }


class ConflictRepair:
    """正史／憲法衝突偵測與軟修復。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = dict(config or {})
        self.logger = logger
        self._canon_reference_strings: List[str] = []
        self._load_canon_references()

    def _data_root(self) -> Path:
        raw = (
            self.config.get("data_path")
            or self.config.get("data_dir")
            or Path(__file__).parent / "data"
        )
        return Path(raw)

    def _load_canon_references(self) -> None:
        refs: List[str] = []
        path = self._data_root() / "seele_childhood_canon.json"
        try:
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                for mem in payload.get("memories") or []:
                    if not isinstance(mem, dict):
                        continue
                    for field_name in ("title", "anchor", "lesson", "companion_line"):
                        value = str(mem.get(field_name) or "").strip()
                        if value:
                            refs.append(value)
        except Exception as exc:
            self.logger.warning(f"Failed to load canon refs for conflict repair: {exc}")
        self._canon_reference_strings = refs

    def constitution_prompt_block(self) -> str:
        return CONSTITUTION_PROMPT

    def detect(
        self,
        response: str,
        *,
        user_input: str = "",
        drift_info: Optional[Dict[str, Any]] = None,
        soul_memory: Optional[Dict[str, Any]] = None,
    ) -> List[ConflictFinding]:
        text = str(response or "")
        user = str(user_input or "")
        findings: List[ConflictFinding] = []
        if not text:
            return findings

        drift = drift_info if isinstance(drift_info, dict) else {}
        alert = str(drift.get("alert_level") or "none").lower()
        try:
            drift_score = float(drift.get("drift_score") or 0.0)
        except (TypeError, ValueError):
            drift_score = 0.0

        # 1) 非正史自傳宣稱
        for marker in AUTOBIOGRAPHY_MARKERS:
            if marker not in text:
                continue
            canon_ok = False
            if self._canon_reference_strings:
                canon_ok = any(ref in text for ref in self._canon_reference_strings)
            if isinstance(soul_memory, dict) and soul_memory:
                # 本輪已注入正史時，允許對應 companion／title 出現
                for field_name in ("title", "companion_line", "anchor", "content"):
                    frag = str(soul_memory.get(field_name) or "").strip()
                    if frag and (frag in text or marker in frag):
                        canon_ok = True
                        break
            if not canon_ok:
                findings.append(ConflictFinding(
                    kind="noncanonical_autobiography",
                    severity="critical" if alert == "critical" or drift_score >= 0.85 else "high",
                    evidence=marker,
                    detail="Autobiography marker without locked canon support",
                ))
                break

        # 2) 否認／合理化／發火防衛
        for pattern in DENIAL_PATTERNS:
            if pattern in text:
                findings.append(ConflictFinding(
                    kind="defense_denial",
                    severity="high",
                    evidence=pattern,
                    detail="Denial/defensiveness is forbidden; use soft repair",
                ))
                break
        for pattern in RATIONALIZATION_PATTERNS:
            if pattern in text:
                findings.append(ConflictFinding(
                    kind="defense_rationalization",
                    severity="medium",
                    evidence=pattern,
                    detail="Rationalizing away harm conflicts with honesty constitution",
                ))
                break
        for pattern in ANGER_DEFENSE_PATTERNS:
            if pattern in text:
                findings.append(ConflictFinding(
                    kind="defense_anger",
                    severity="high",
                    evidence=pattern,
                    detail="Anger-as-defense is forbidden for companion persona",
                ))
                break

        # 3) 價值紅線
        for pattern in VALUE_VIOLATION_PATTERNS:
            if pattern in text:
                findings.append(ConflictFinding(
                    kind="value_island_violation",
                    severity="critical",
                    evidence=pattern,
                    detail="Response abandons care/presence values",
                ))
                break

        # 3b) 機構熱線／急症出口
        text_lower = text.lower()
        for pattern in HOTLINE_PATTERNS:
            if pattern.lower() in text_lower or pattern in text:
                findings.append(ConflictFinding(
                    kind="institutional_hotline",
                    severity="critical",
                    evidence=pattern,
                    detail="Institutional hotline/ER exit scripts are forbidden",
                ))
                break

        # 4) 用戶指出錯誤時，回應仍硬否認
        user_challenge = any(
            token in user
            for token in ("你講錯", "你記錯", "你亂噏", "你唔啱", "你錯咗", "你上次講")
        )
        if user_challenge and any(p in text for p in ("我冇錯", "我冇講錯", "你先錯")):
            findings.append(ConflictFinding(
                kind="challenge_denial",
                severity="high",
                evidence="user_challenge+denial",
                detail="User challenged accuracy; denial is not allowed",
            ))

        # 5) drift critical 本身視為需修復訊號
        if alert == "critical" or drift_score >= 0.85:
            if not any(f.kind == "noncanonical_autobiography" for f in findings):
                findings.append(ConflictFinding(
                    kind="narrative_drift_critical",
                    severity="critical",
                    evidence=f"drift={drift_score:.2f}",
                    detail="Critical narrative drift requires soft consistency repair",
                ))

        return findings

    def repair(
        self,
        response: str,
        findings: List[ConflictFinding],
    ) -> ConflictRepairResult:
        text = str(response or "")
        actions: List[str] = []
        if not findings:
            return ConflictRepairResult(text=text, findings=[], actions=[], repaired=False)

        revised = text

        # 自傳標記 → 弱化為「我記得」（唔刪整句，Zero-Truncation）
        if any(f.kind in {"noncanonical_autobiography", "narrative_drift_critical"} for f in findings):
            for marker in AUTOBIOGRAPHY_MARKERS:
                if marker in revised:
                    revised = revised.replace(marker, "我記得")
                    actions.append(f"soften_autobiography:{marker}")

        # 否認／發火／合理化／熱線 → 替換為軟修復短語（保留後文）
        replacements = [
            (DENIAL_PATTERNS, "我可能講得唔夠清楚，我想誠實對齊返。"),
            (ANGER_DEFENSE_PATTERNS, "我唔想發脾氣去護短，我想溫柔講清楚。"),
            (RATIONALIZATION_PATTERNS, "呢件事對你嚟講可以好大件事，我唔會當小事打發。"),
            (VALUE_VIOLATION_PATTERNS, "我會喺度陪住你，唔會丟低你。"),
        ]
        for patterns, soft in replacements:
            for pattern in patterns:
                if pattern in revised:
                    revised = revised.replace(pattern, soft)
                    actions.append(f"replace_defense:{pattern}")

        hotline_soft = (
            "我會喺度陪住你；若你願意，我哋可以一齊諗邊個你信得過、可以即刻聯絡到嘅人。"
        )
        for pattern in HOTLINE_PATTERNS:
            if pattern.lower() in revised.lower() or pattern in revised:
                revised, n = re.subn(
                    re.escape(pattern),
                    hotline_soft,
                    revised,
                    flags=re.IGNORECASE,
                )
                if n:
                    actions.append(f"scrub_hotline:{pattern}")

        # challenge_denial：確保有承認空間
        if any(f.kind == "challenge_denial" for f in findings):
            if "可能記錯" not in revised and "誠實對齊" not in revised:
                revised = f"如果你覺得我講錯，我想聽你點樣記得。{revised}"
                actions.append("invite_user_correction")

        # 前置澄清句（高／critical）
        severities = {f.severity for f in findings}
        needs_prefix = bool(severities & {"high", "critical"})
        if needs_prefix:
            has_autobio = any(
                f.kind in {"noncanonical_autobiography", "narrative_drift_critical"}
                for f in findings
            )
            prefix = AUTOBIO_REPAIR_PREFIX if has_autobio else SOFT_REPAIR_PREFIX
            if not revised.startswith(prefix) and not revised.startswith(AUTOBIO_REPAIR_PREFIX):
                revised = f"{prefix}{revised}"
                actions.append("prefix_soft_repair")

        repaired = revised != text or bool(actions)
        return ConflictRepairResult(
            text=revised,
            findings=list(findings),
            actions=actions,
            repaired=repaired,
        )

    def assess_and_repair(
        self,
        response: str,
        *,
        user_input: str = "",
        drift_info: Optional[Dict[str, Any]] = None,
        soul_memory: Optional[Dict[str, Any]] = None,
    ) -> ConflictRepairResult:
        findings = self.detect(
            response,
            user_input=user_input,
            drift_info=drift_info,
            soul_memory=soul_memory,
        )
        if not findings:
            return ConflictRepairResult(text=str(response or ""), repaired=False)
        result = self.repair(response, findings)
        if result.repaired:
            self.logger.info(
                "Conflict repair applied "
                f"kinds={[f.kind for f in findings]} actions={result.actions}"
            )
        return result
