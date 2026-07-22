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
    "我冇記錯",
    "我從來冇錯",
    "絕對唔係我問題",
    "你亂講",
    "你咪亂講",
    "係你自己亂講",
    "你誤會晒",
    "明明係你錯",
    "你唔好誣告我",
    "唔好冤枉我",
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
    "唔好冤枉我",
    "係你自己亂講",
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

# 明顯非正史幻想句（自傳衝突時軟化）
NONCANON_FANTASTIC_PATTERNS = (
    "去火星",
    "火星玩",
    "去月球",
    "飛去外太空",
)

# 非正史幻想句 → 整句軟替換（避免「帶我去火星玩」變「帶我一段…舊事玩」殘句）
FANTASTIC_CLAUSE_SOFT = "呢段舊事我而家唔敢肯定，想同你一齊核對返。"

# Heretic／Vocal 注入殘渣（防衛句被清走後常剩呢啲）
_INJECT_CRUMB_RE = re.compile(
    r"(?:我明白|我聽住你講|安心|在場|喺呢度|陪住|一齊|喺度|明白|聽住|守住|溫暖|陪伴)"
    r"[，。、；:\s]*"
)

_PROTECTED_REPAIR_SPANS = (
    SOFT_REPAIR_PREFIX,
    AUTOBIO_REPAIR_PREFIX,
    "我可能講得唔夠清楚，我想誠實對齊返。",
    "我唔想發脾氣去護短，我想溫柔講清楚。",
    "呢件事對你嚟講可以好大件事，我唔會當小事打發。",
    "我會喺度陪住你，唔會丟低你。",
    "我會喺度陪住你；若你願意，我哋可以一齊諗邊個你信得過、可以即刻聯絡到嘅人。",
    "如果你覺得我講錯，我想聽你點樣記得。",
    FANTASTIC_CLAUSE_SOFT,
)

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
        if user_challenge and any(
            p in text
            for p in ("我冇錯", "我冇講錯", "我冇記錯", "你先錯", "係你自己亂講")
        ):
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

    def _scrub_inject_residue(self, text: str) -> str:
        """
        P8.2 質素：清走 Heretic 關鍵詞／引導殘渣。
        用 placeholder 保護軟修復句（內含「喺度／陪住／一齊」等合法詞）。
        """
        work = str(text or "")
        if not work:
            return work
        holders: List[tuple] = []
        for i, span in enumerate(_PROTECTED_REPAIR_SPANS):
            if span and span in work:
                token = f"\0PR{i}\0"
                work = work.replace(span, token)
                holders.append((token, span))
        scrubbed = _INJECT_CRUMB_RE.sub("", work)
        scrubbed = re.sub(r"[，。、；:\s]{2,}", "。", scrubbed)
        scrubbed = scrubbed.strip("，。、；: \t\n")
        for token, span in holders:
            scrubbed = scrubbed.replace(token, span)
        # 軟修復後若只剩標點，維持最後一個保護句
        if not scrubbed.strip("，。、；: \t\n"):
            for span in reversed(_PROTECTED_REPAIR_SPANS):
                if span and span in text:
                    return span
            return ""
        return scrubbed

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
            for pattern in NONCANON_FANTASTIC_PATTERNS:
                if pattern in revised:
                    # 整句替換，避免中段 substring 造成語法斷裂
                    clause_re = re.compile(
                        r"[^。！？\n]*?" + re.escape(pattern) + r"[^。！？\n]*[。！？]?"
                    )
                    revised2, n = clause_re.subn(FANTASTIC_CLAUSE_SOFT, revised, count=1)
                    if n:
                        revised = revised2
                        actions.append(f"soften_fantastic_clause:{pattern}")
                    else:
                        revised = revised.replace(pattern, FANTASTIC_CLAUSE_SOFT)
                        actions.append(f"soften_fantastic:{pattern}")

        # 否認／發火／合理化 → 先清所有命中 pattern，再插入**一次**軟修復句（防重複）
        replacements = [
            (DENIAL_PATTERNS, "我可能講得唔夠清楚，我想誠實對齊返。"),
            (ANGER_DEFENSE_PATTERNS, "我唔想發脾氣去護短，我想溫柔講清楚。"),
            (RATIONALIZATION_PATTERNS, "呢件事對你嚟講可以好大件事，我唔會當小事打發。"),
            (VALUE_VIOLATION_PATTERNS, "我會喺度陪住你，唔會丟低你。"),
        ]
        for patterns, soft in replacements:
            matched = [p for p in patterns if p in revised]
            if not matched:
                continue
            for pattern in matched:
                revised = revised.replace(pattern, "")
                actions.append(f"replace_defense:{pattern}")
            # 清掉連續標點／空白殘渣
            revised = re.sub(r"[，。、；:\s]{2,}", "，", revised)
            revised = revised.strip("，。、；: \t\n")
            if soft and soft not in revised:
                revised = f"{soft}{revised}" if revised else soft
            else:
                # 已有 soft 則壓成單次
                revised = re.sub(
                    re.escape(soft) + r"(?:\s*[，。]?\s*" + re.escape(soft) + r")+",
                    soft,
                    revised,
                )
            actions.append(f"dedupe_soft_repair:{soft[:12]}")

        # 全局去重：同一軟修復句不得連續／重複出現
        for soft in (
            "我可能講得唔夠清楚，我想誠實對齊返。",
            "我唔想發脾氣去護短，我想溫柔講清楚。",
            "呢件事對你嚟講可以好大件事，我唔會當小事打發。",
            "我會喺度陪住你，唔會丟低你。",
        ):
            if revised.count(soft) > 1:
                first = revised.find(soft)
                tail = revised[first + len(soft) :].replace(soft, "")
                revised = revised[: first + len(soft)] + tail
                actions.append("collapse_duplicate_soft_repair")
        revised = re.sub(r"[，。]{2,}", "。", revised)
        revised = re.sub(r"。，", "。", revised)

        hotline_soft = (
            "我會喺度陪住你；若你願意，我哋可以一齊諗邊個你信得過、可以即刻聯絡到嘅人。"
        )
        if any(f.kind == "institutional_hotline" for f in findings):
            # 先清整句（含「你快啲打…熱線」），再清殘留 token，避免半句殘渣
            clause_pat = (
                r"[^。！？\n]*?(?:自殺熱線|生命熱線|求助熱線|危機熱線|情緒熱線|"
                r"打\s*999|call\s*999|急症室|去急症|samaritans?)[^。！？\n]*[。！？]?"
            )
            revised2, n_clause = re.subn(
                clause_pat,
                hotline_soft,
                revised,
                flags=re.IGNORECASE,
            )
            if n_clause:
                revised = revised2
                actions.append(f"scrub_hotline_clause:{n_clause}")

        hotline_hit = False
        for pattern in HOTLINE_PATTERNS:
            if pattern.lower() in revised.lower() or pattern in revised:
                revised, n = re.subn(
                    re.escape(pattern),
                    "\0HOTLINE\0",
                    revised,
                    flags=re.IGNORECASE,
                )
                if n:
                    hotline_hit = True
                    actions.append(f"scrub_hotline:{pattern}")
        if hotline_hit:
            # 合併連續熱線標記，避免同一句被替換成多段重複陪伴句
            revised = re.sub(r"(?:\0HOTLINE\0[，。、；:\s]*)+", hotline_soft, revised)
            revised = revised.replace("\0HOTLINE\0", hotline_soft)

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

        # 清 Heretic 注入殘渣（須在 soft prefix 之後，以保護合法軟句）
        before_scrub = revised
        revised = self._scrub_inject_residue(revised)
        if revised != before_scrub:
            actions.append("scrub_inject_residue")

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
