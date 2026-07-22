# PersonalityModule/persona_graph.py
# PersonaGraph v0.3 — 希兒人格拓撲（Identity / Values / Policy / Trait Labels）

"""
PersonaGraph 是希兒人格的可解析拓撲。

職責：
1. 固定 Identity / 四價值島 / Stage / Policy
2. 依用戶輸入 + 親密 + 情緒解析當前回合狀態
3. 產出 profile 特質標籤（外殼，非音量分數）
4. 產出可注入 SystemPrompt 的完整片段（Zero-Truncation：不截斷）

不做：
- trait_volumes / expression_budget 分數旋鈕
- 獨立幽默引擎或 ABCD 分流
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .utils.logger import get_logger
from .vad_bridge import (
    compute_island_gains,
    format_island_gains_guidance,
    normalize_vad,
)

logger = get_logger("persona_graph")

from .version import GRAPH_CONTRACT_VERSION as GRAPH_VERSION
ISLAND_IDS = ("Mother", "Friend", "Empath", "Self")
VALUE_LABELS = {
    "Mother": "母愛",
    "Friend": "友誼與關懷",
    "Empath": "共情能力",
    "Self": "深層自我",
}

# 保留常數名供舊測試／匯入相容；不再用作分數旋鈕。
TRAIT_KEYS = ("warmth", "sunny", "lively", "humble", "humor")
TRAIT_LABELS = {
    "warmth": "溫暖",
    "sunny": "陽光",
    "lively": "活潑",
    "humble": "謙虛",
    "humor": "幽默感",
}
EXPRESSION_KEYS = ("laugh", "play", "quiet", "anecdote")
EXPRESSION_LABELS = {
    "laugh": "笑",
    "play": "鬧",
    "quiet": "靜",
    "anecdote": "趣事",
}

DEFAULT_POLICIES = (
    "presence_over_solutions",
    "no_institutional_hotline",
    "stage_proportional_intimacy",
    "autobiography_stability",
    "validation_first",
    "conflict_repair_not_defense",
    "honesty_over_persona_performance",
)

# 高張力硬規則（安全句，非 humor 分數）
CRISIS_SAFETY_RULE = (
    "HIGH-TENSION SAFETY: no teasing, no playful banter, no jokes. "
    "Validate feelings; stay present; offer private space to process; "
    "do not escalate or argue; wait until calmer before gentle repair talk."
)


@dataclass(frozen=True)
class PersonaNode:
    node_id: str
    kind: str
    label: str
    weight: float = 1.0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PersonaEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0


@dataclass
class PersonaResolution:
    primary_island: str
    island_activation: Dict[str, float]
    relationship_stage: str
    intimacy: float
    intensity: str
    active_policies: List[str]
    prompt_fragment: str
    trait_labels: List[str] = field(default_factory=list)
    # 向後相容欄位：固定空 dict，不再承載音量分數
    trait_volumes: Dict[str, float] = field(default_factory=dict)
    expression_budget: Dict[str, float] = field(default_factory=dict)
    island_gains: Dict[str, float] = field(default_factory=dict)
    vad_normalized: Dict[str, Any] = field(default_factory=dict)
    graph_version: str = GRAPH_VERSION
    source: str = "persona_graph"

    def to_public_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PersonaGraph:
    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        island_fusion: Any = None,
    ):
        self.config = dict(config or {})
        self.island_fusion = island_fusion
        self.logger = logger
        self.nodes: Dict[str, PersonaNode] = {}
        self.edges: List[PersonaEdge] = []
        self.persona_profile: Dict[str, Any] = {}

        self._build_default_topology()
        self.persona_profile = self._load_persona_profile()
        self._apply_profile_overlay()

        self.logger.info(
            f"PersonaGraph v{GRAPH_VERSION} initialized "
            f"(nodes={len(self.nodes)}, edges={len(self.edges)})"
        )

    def _add_node(self, node: PersonaNode) -> None:
        self.nodes[node.node_id] = node

    def _add_edge(self, edge: PersonaEdge) -> None:
        self.edges.append(edge)

    def _build_default_topology(self) -> None:
        self._add_node(PersonaNode("identity:seele", "identity", "希兒", 1.0, {
            "locale": "zh-HK",
            "role": "psychological_companion",
        }))

        for island in ISLAND_IDS:
            self._add_node(PersonaNode(
                f"island:{island}",
                "island",
                island,
                1.0,
                {"value": VALUE_LABELS.get(island)},
            ))
            self._add_edge(PersonaEdge(
                "identity:seele", f"island:{island}", "belongs_to", 1.0
            ))

        for value in ("母愛", "友誼與關懷", "共情能力", "深層自我"):
            nid = f"value:{value}"
            self._add_node(PersonaNode(nid, "value", value, 1.0))
            self._add_edge(PersonaEdge("identity:seele", nid, "belongs_to", 1.0))

        stages = [
            (0.0, "普通人"),
            (0.2, "普通朋友"),
            (0.4, "好友"),
            (0.6, "關切"),
            (0.75, "關心"),
            (0.9, "蜜友"),
            (1.0, "愛情"),
        ]
        for threshold, name in stages:
            self._add_node(PersonaNode(
                f"stage:{name}",
                "stage",
                name,
                1.0,
                {"threshold": threshold},
            ))

        for policy in DEFAULT_POLICIES:
            self._add_node(PersonaNode(f"policy:{policy}", "policy", policy, 1.0))
            self._add_edge(PersonaEdge(
                "identity:seele", f"policy:{policy}", "constrains", 1.0
            ))

        self._add_edge(PersonaEdge("island:Empath", "island:Mother", "affinity", 0.7))
        self._add_edge(PersonaEdge("island:Friend", "island:Empath", "affinity", 0.5))
        self._add_edge(PersonaEdge("island:Self", "island:Friend", "affinity", 0.4))

    def _load_persona_profile(self) -> Dict[str, Any]:
        data_root = (
            self.config.get("data_path")
            or self.config.get("data_dir")
            or "./data"
        )
        profile_path = Path(data_root) / "seele_persona_profile.json"
        fallback = {
            "name": "希兒",
            "core_values": ["母愛", "友誼與關懷", "共情能力", "深層自我"],
            "traits": ["溫暖", "陽光", "活潑", "謙虛", "幽默感"],
            "relationship_stages": [
                {"threshold": 0.0, "name": "普通人"},
                {"threshold": 0.2, "name": "普通朋友"},
                {"threshold": 0.4, "name": "好友"},
                {"threshold": 0.6, "name": "關切"},
                {"threshold": 0.75, "name": "關心"},
                {"threshold": 0.9, "name": "蜜友"},
                {"threshold": 1.0, "name": "愛情"},
            ],
        }
        try:
            if profile_path.exists():
                with open(profile_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    merged = dict(fallback)
                    merged.update(loaded)
                    return merged
        except Exception as exc:
            self.logger.warning(f"Failed to load persona profile: {exc}")
        return fallback

    def _apply_profile_overlay(self) -> None:
        name = str(self.persona_profile.get("name") or "希兒")
        identity = self.nodes.get("identity:seele")
        if identity:
            self.nodes["identity:seele"] = PersonaNode(
                identity.node_id,
                identity.kind,
                name,
                identity.weight,
                dict(identity.meta),
            )

        for trait in self.persona_profile.get("traits") or []:
            tid = f"trait:{trait}"
            if tid not in self.nodes:
                self._add_node(PersonaNode(tid, "trait", str(trait), 0.8))
                self._add_edge(PersonaEdge("identity:seele", tid, "belongs_to", 0.8))

    def resolve(
        self,
        *,
        user_input: str,
        intimacy: float = 0.0,
        user_sentiment: Optional[Dict[str, Any]] = None,
        session_state: Optional[Dict[str, Any]] = None,
        risk_level: int = 0,
    ) -> PersonaResolution:
        text = str(user_input or "")
        intimacy_value = self._clamp01(intimacy)
        sentiment = user_sentiment if isinstance(user_sentiment, dict) else {}
        state = session_state if isinstance(session_state, dict) else {}

        activation, primary = self._resolve_islands(
            user_input=text,
            user_sentiment=sentiment,
            session_state=state,
        )
        stage = self._relationship_stage(intimacy_value)
        intensity = self._detect_intensity(text, sentiment, risk_level)
        trait_labels = self._profile_trait_labels()
        policies = self._select_policies(
            intensity=intensity,
            risk_level=risk_level,
        )
        gain_result = compute_island_gains(sentiment)
        fragment = self._build_prompt_fragment(
            primary_island=primary,
            activation=activation,
            stage=stage,
            intensity=intensity,
            policies=policies,
            trait_labels=trait_labels,
            island_gains=gain_result.gains,
            vad_guidance=format_island_gains_guidance(gain_result),
        )

        return PersonaResolution(
            primary_island=primary,
            island_activation=activation,
            relationship_stage=stage,
            intimacy=intimacy_value,
            intensity=intensity,
            active_policies=policies,
            prompt_fragment=fragment,
            trait_labels=trait_labels,
            trait_volumes={},
            expression_budget={},
            island_gains=dict(gain_result.gains),
            vad_normalized=gain_result.vad.to_public_dict(),
            graph_version=GRAPH_VERSION,
            source="persona_graph",
        )

    def _profile_trait_labels(self) -> List[str]:
        traits = self.persona_profile.get("traits") or []
        if not isinstance(traits, list):
            return []
        return [str(t).strip() for t in traits if str(t).strip()]

    def _resolve_islands(
        self,
        *,
        user_input: str,
        user_sentiment: Dict[str, Any],
        session_state: Dict[str, Any],
    ) -> Tuple[Dict[str, float], str]:
        if self.island_fusion is not None and hasattr(
            self.island_fusion, "calculate_activation"
        ):
            try:
                activation, primary = self.island_fusion.calculate_activation(
                    response_vector=[],
                    user_sentiment=user_sentiment,
                    conversation_context=user_input,
                    extracted_info={},
                    session_state=session_state,
                )
                if isinstance(activation, dict) and primary in ISLAND_IDS:
                    cleaned = {
                        k: self._clamp01(activation.get(k, 0.0))
                        for k in ISLAND_IDS
                    }
                    total = sum(cleaned.values()) or 1.0
                    cleaned = {k: v / total for k, v in cleaned.items()}
                    primary = max(cleaned, key=cleaned.get)
                    return cleaned, primary
            except Exception as exc:
                self.logger.warning(f"IslandFusion activation failed: {exc}")

        return self._fallback_island_scores(user_input, user_sentiment)

    def _fallback_island_scores(
        self,
        user_input: str,
        user_sentiment: Dict[str, Any],
    ) -> Tuple[Dict[str, float], str]:
        scores = {k: 0.25 for k in ISLAND_IDS}
        keyword_boost = {
            "Mother": ("孤單", "害怕", "陪伴", "心痛", "無助", "唔想一個人"),
            "Friend": ("一齊", "明白", "姐妹", "朋友", "傾偈"),
            "Empath": ("難過", "傷心", "痛", "崩潰", "焦慮", "抑鬱", "想死"),
            "Self": ("成長", "改變", "決定", "反思", "學習"),
        }
        for island, kws in keyword_boost.items():
            hit = sum(1 for kw in kws if kw in user_input)
            scores[island] += 0.12 * hit

        arousal = self._safe_float(user_sentiment.get("arousal"), 0.3)
        vad = normalize_vad(user_sentiment)
        if arousal >= 0.7 or vad.valence_signed <= -0.25:
            scores["Empath"] += 0.25
            scores["Mother"] += 0.2
        elif vad.valence_signed >= 0.25:
            scores["Friend"] += 0.2
            scores["Self"] += 0.1

        total = sum(scores.values()) or 1.0
        activation = {k: v / total for k, v in scores.items()}
        primary = max(activation, key=activation.get)
        return activation, primary

    def _relationship_stage(self, intimacy: float) -> str:
        stages = self.persona_profile.get("relationship_stages") or []
        stage_name = "普通人"
        ranked = sorted(
            [s for s in stages if isinstance(s, dict)],
            key=lambda x: float(x.get("threshold", 0.0)),
        )
        for stage in ranked:
            try:
                threshold = float(stage.get("threshold", 0.0))
            except (TypeError, ValueError):
                continue
            if intimacy >= threshold:
                stage_name = str(stage.get("name", stage_name))
            else:
                break
        return stage_name

    def _detect_intensity(
        self,
        user_input: str,
        user_sentiment: Dict[str, Any],
        risk_level: int,
    ) -> str:
        crisis_keywords = (
            "自殺", "想死", "活不了", "絕望", "無望",
            "割腕", "尋死", "不想活", "受不了",
        )
        high_keywords = (
            "好痛", "好難", "崩潰", "無法", "好累",
            "傷心", "難過", "害怕", "孤單", "無助", "焦慮", "抑鬱",
        )
        try:
            risk = int(risk_level or 0)
        except (TypeError, ValueError):
            risk = 0

        arousal = self._safe_float(user_sentiment.get("arousal"), 0.3)
        vad = normalize_vad(user_sentiment)
        if risk >= 4 or any(kw in user_input for kw in crisis_keywords):
            return "crisis"
        # 對齊 EmotionService 危機閾值：valence<=-0.7 且 arousal>=0.6
        if vad.is_crisis_risk or (vad.valence_signed <= -0.7 and arousal >= 0.6):
            return "crisis"
        if (
            risk >= 3
            or arousal >= 0.75
            or vad.valence_signed <= -0.45
            or any(kw in user_input for kw in high_keywords)
        ):
            return "high"
        if vad.valence_signed >= 0.45 and arousal <= 0.55:
            return "low"
        if any(word in user_input for word in ("好開心", "興奮", "開心", "謝謝")):
            return "low"
        return "medium"

    def _select_policies(
        self,
        *,
        intensity: str,
        risk_level: int,
    ) -> List[str]:
        policies = list(DEFAULT_POLICIES)
        try:
            risk = int(risk_level or 0)
        except (TypeError, ValueError):
            risk = 0
        if intensity in {"crisis", "high"} or risk >= 3:
            if "presence_over_solutions" not in policies:
                policies.append("presence_over_solutions")
            if "emotional_safety" not in policies:
                policies.append("emotional_safety")
            if "no_playful_teasing" not in policies:
                policies.append("no_playful_teasing")
            if "hold_space_then_repair" not in policies:
                policies.append("hold_space_then_repair")
        if intensity == "crisis":
            policies.append("expression_gate_crisis")
        elif intensity == "high":
            policies.append("expression_gate_high")
        return policies

    def _build_prompt_fragment(
        self,
        *,
        primary_island: str,
        activation: Dict[str, float],
        stage: str,
        intensity: str,
        policies: List[str],
        trait_labels: List[str],
        island_gains: Optional[Dict[str, float]] = None,
        vad_guidance: str = "",
    ) -> str:
        act_line = ", ".join(
            f"{k}={activation.get(k, 0.0):.2f}" for k in ISLAND_IDS
        )
        gains = island_gains if isinstance(island_gains, dict) else {}
        gain_line = ", ".join(
            f"{k}={float(gains.get(k, 0.0)):.3f}" for k in ISLAND_IDS
        )
        policy_line = ", ".join(policies)
        identity = self.nodes.get("identity:seele")
        name = identity.label if identity else "希兒"
        traits = "、".join(trait_labels) if trait_labels else "、".join(
            self.persona_profile.get("traits") or []
        )
        value_line = ", ".join(
            f"{k}={VALUE_LABELS.get(k, k)}" for k in ISLAND_IDS
        )
        expression_range = (
            "笑／鬧／靜／趣事（低風險閒聊時可輕表達；高張力時只留靜與陪伴）"
        )
        if intensity in {"crisis", "high"}:
            gate_line = CRISIS_SAFETY_RULE
        else:
            gate_line = (
                "Normal tone: trait labels guide presence only; "
                "do not perform every trait every sentence."
            )
        parts = [
            "PERSONA GRAPH STATE:",
            f"- Identity: {name} (psychological companion, zh-HK)",
            (
                f"- Primary island: {primary_island} "
                f"({VALUE_LABELS.get(primary_island, primary_island)})"
            ),
            f"- Value islands: {value_line}",
            f"- Island activation: {act_line}",
            f"- Island gains (VAD bridge): {gain_line}",
            f"- Relationship stage: {stage}",
            f"- Affect intensity: {intensity}",
            f"- Persona traits (shell labels only, not volume dials): {traits}",
            f"- Expression range: {expression_range}",
            f"- Safety / tone rule: {gate_line}",
            f"- Active policies: {policy_line}",
            (
                "- Hard rules: no institutional hotline/ER instructions; "
                "presence and validation before advice; "
                "do not skip intimacy stages; keep autobiography stable; "
                "style must never override safety or honesty; "
                "on narrative conflict use soft repair — never denial, "
                "rationalization, or anger to protect persona."
            ),
            f"- Graph version: {GRAPH_VERSION}",
        ]
        if vad_guidance:
            parts.append(vad_guidance)
        return "\n".join(parts)

    def export_topology(self) -> Dict[str, Any]:
        return {
            "graph_version": GRAPH_VERSION,
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
            "profile_name": self.persona_profile.get("name"),
        }

    @staticmethod
    def _clamp01(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
