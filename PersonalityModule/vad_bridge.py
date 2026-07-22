# PersonalityModule/vad_bridge.py
# P6.1 — EmotionService VAD → 四島增益（統一刻度）

"""
EmotionService 契約：
  valence / dominance: [-1, 1]（0 = 中性）
  arousal: [0, 1]

歷史問題：
  IslandFusion / PersonaGraph 曾把 valence 當 [0,1]、中性 0.5，
  導致 EmotionService 的 0.0（中性）被誤判為負向。

本模組職責：
  1. 正規化 VAD（辨識 signed / unit，輸出雙刻度）
  2. 由 VAD + dominant_emotion / emotion_vector / 24-dim 計算四島增益
  3. Zero-Truncation：完整回傳結構，不做字串截斷
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ISLAND_IDS: Tuple[str, ...] = ("Mother", "Friend", "Empath", "Self")

# EmotionService 10 維 → Plutchik／親和表鍵
_LABEL_TO_AFFINITY_KEY = {
    "joy": "joy",
    "sad": "sadness",
    "sadness": "sadness",
    "hope": "anticipation",
    "fear": "fear",
    "despair": "sadness",
    "desire": "anticipation",
    "pride": "joy",
    "humility": "trust",
    "love": "trust",
    "hate": "anger",
    "trust": "trust",
    "anger": "anger",
    "surprise": "surprise",
    "disgust": "disgust",
    "anticipation": "anticipation",
    "anxiety": "fear",
    "loneliness": "sadness",
    "calm": "trust",
    "shame": "sadness",
    "guilt": "sadness",
    "relief": "joy",
    "frustration": "anger",
    "contentment": "joy",
    "excitement": "anticipation",
}

# 島 × 情緒親和（與 IslandFusion.emotion_affinity 對齊，供向量加權）
_ISLAND_EMOTION_AFFINITY: Dict[str, Dict[str, float]] = {
    "Mother": {
        "joy": 0.6, "trust": 0.9, "fear": 0.95, "surprise": 0.4,
        "sadness": 0.85, "disgust": 0.3, "anger": 0.4, "anticipation": 0.5,
    },
    "Friend": {
        "joy": 0.9, "trust": 0.8, "fear": 0.7, "surprise": 0.7,
        "sadness": 0.8, "disgust": 0.5, "anger": 0.6, "anticipation": 0.8,
    },
    "Empath": {
        "joy": 0.7, "trust": 0.85, "fear": 0.8, "surprise": 0.5,
        "sadness": 0.95, "disgust": 0.6, "anger": 0.7, "anticipation": 0.6,
    },
    "Self": {
        "joy": 0.8, "trust": 0.85, "fear": 0.6, "surprise": 0.6,
        "sadness": 0.7, "disgust": 0.4, "anger": 0.5, "anticipation": 0.85,
    },
}


@dataclass
class NormalizedVAD:
    """雙刻度 VAD；Zero-Truncation：完整欄位。"""
    valence_signed: float
    arousal: float
    dominance_signed: float
    valence_unit: float  # 0..1，0.5 = 中性
    scale_detected: str  # signed | unit | mixed
    dominant_emotion: str = "neutral"
    is_crisis_risk: bool = False
    confidence: float = 0.0
    method: str = ""
    polarity: str = "neutral"  # positive | negative | neutral
    affect_intensity: float = 0.0  # 0..1 情緒強度

    def to_public_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IslandGainResult:
    gains: Dict[str, float]
    primary_island: str
    vad: NormalizedVAD
    sources: List[str] = field(default_factory=list)
    version: str = "1.0.0"

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "gains": dict(self.gains),
            "primary_island": self.primary_island,
            "vad": self.vad.to_public_dict(),
            "sources": list(self.sources),
            "version": self.version,
        }


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def detect_vad_scale(sentiment: Dict[str, Any]) -> str:
    """
    判斷 valence 刻度。
    - 顯式 vad_scale / valence_scale 優先
    - valence < 0 或 > 1 → signed（>1 會再 clamp）
    - EmotionService 欄位齊全且 valence==0.0 中性 → signed
    - orchestrator 舊預設 0.5 且無 EmotionService 標記 → unit
    """
    if not isinstance(sentiment, dict):
        return "unit"

    explicit = str(
        sentiment.get("vad_scale")
        or sentiment.get("valence_scale")
        or ""
    ).strip().lower()
    if explicit in {"signed", "unit"}:
        return explicit

    valence = _safe_float(sentiment.get("valence"), 0.0)
    if valence < 0.0 or valence > 1.0:
        return "signed"

    method = str(sentiment.get("method") or "").lower()
    has_emo_markers = any(
        k in sentiment
        for k in (
            "dominant_emotion",
            "is_crisis_risk",
            "emotion_vector",
            "emotion_dimensions",
            "detected_crisis_keywords",
        )
    )
    # EmotionService 中性為 0.0；orchestrator 舊 fallback 中性為 0.5
    if has_emo_markers or method in {"api", "heuristic", "fallback", "emobloom"}:
        return "signed"
    if abs(valence - 0.5) < 1e-9 and not has_emo_markers:
        return "unit"
    # 落在 (0,1) 的模糊值：若同時有 dominance∈[-1,1] 且 |dominance|>0.05 → signed
    dominance = sentiment.get("dominance")
    if dominance is not None:
        d = _safe_float(dominance, 0.0)
        if d < 0.0 or d > 1.0 or (method and method != "unknown"):
            return "signed"
    return "unit"


def normalize_vad(user_sentiment: Optional[Dict[str, Any]]) -> NormalizedVAD:
    sentiment = user_sentiment if isinstance(user_sentiment, dict) else {}
    scale = detect_vad_scale(sentiment)

    raw_v = _safe_float(sentiment.get("valence"), 0.0 if scale == "signed" else 0.5)
    raw_a = _safe_float(sentiment.get("arousal"), 0.5 if scale == "signed" else 0.3)
    raw_d = _safe_float(sentiment.get("dominance"), 0.0 if scale == "signed" else 0.5)

    if scale == "unit":
        valence_unit = _clamp(raw_v, 0.0, 1.0)
        valence_signed = _clamp(valence_unit * 2.0 - 1.0, -1.0, 1.0)
        # unit 路徑下 dominance 亦可能是 0..1
        if 0.0 <= raw_d <= 1.0 and "dominance" in sentiment:
            dominance_signed = _clamp(raw_d * 2.0 - 1.0, -1.0, 1.0)
        else:
            dominance_signed = _clamp(raw_d, -1.0, 1.0)
    else:
        valence_signed = _clamp(raw_v, -1.0, 1.0)
        valence_unit = _clamp((valence_signed + 1.0) / 2.0, 0.0, 1.0)
        dominance_signed = _clamp(raw_d, -1.0, 1.0)

    arousal = _clamp(raw_a, 0.0, 1.0)

    if valence_signed <= -0.25:
        polarity = "negative"
    elif valence_signed >= 0.25:
        polarity = "positive"
    else:
        polarity = "neutral"

    # 強度：偏離中性 + 喚醒
    affect_intensity = _clamp(abs(valence_signed) * 0.65 + arousal * 0.45, 0.0, 1.0)

    return NormalizedVAD(
        valence_signed=valence_signed,
        arousal=arousal,
        dominance_signed=dominance_signed,
        valence_unit=valence_unit,
        scale_detected=scale,
        dominant_emotion=str(sentiment.get("dominant_emotion") or "neutral").lower().strip(),
        is_crisis_risk=bool(sentiment.get("is_crisis_risk", False)),
        confidence=_safe_float(sentiment.get("confidence"), 0.0),
        method=str(sentiment.get("method") or ""),
        polarity=polarity,
        affect_intensity=affect_intensity,
    )


def _base_gains_from_vad(vad: NormalizedVAD) -> Dict[str, float]:
    """VAD 主路徑：負向高喚醒 → Mother/Empath；正向 → Friend/Self。"""
    gains = {k: 0.35 for k in ISLAND_IDS}
    v = vad.valence_signed
    a = vad.arousal
    d = vad.dominance_signed

    if v <= -0.25:
        neg = abs(v)
        gains["Mother"] += 0.25 + neg * 0.35
        gains["Empath"] += 0.22 + neg * 0.40
        gains["Friend"] += 0.05
        gains["Self"] += 0.02
        if a >= 0.65:
            gains["Empath"] += 0.18
            gains["Mother"] += 0.12
        if d <= -0.35:
            gains["Mother"] += 0.10
            gains["Empath"] += 0.08
    elif v >= 0.25:
        pos = v
        gains["Friend"] += 0.22 + pos * 0.35
        gains["Self"] += 0.15 + pos * 0.25
        gains["Mother"] += 0.05
        gains["Empath"] += 0.04
        if a >= 0.55:
            gains["Friend"] += 0.10
            gains["Self"] += 0.08
    else:
        # 近中性：略偏 Empath 陪伴，避免全平
        gains["Empath"] += 0.08
        gains["Friend"] += 0.06
        if a >= 0.7:
            gains["Empath"] += 0.12
            gains["Mother"] += 0.08

    if vad.is_crisis_risk or (v <= -0.7 and a >= 0.6):
        gains["Mother"] += 0.25
        gains["Empath"] += 0.30
        gains["Friend"] = max(0.05, gains["Friend"] * 0.55)
        gains["Self"] = max(0.05, gains["Self"] * 0.55)

    return gains


def _gains_from_emotion_labels(
    sentiment: Dict[str, Any],
    base: Dict[str, float],
) -> Tuple[Dict[str, float], List[str]]:
    """用 dominant / 10-dim / 24-dim 微調增益。"""
    sources: List[str] = []
    gains = dict(base)

    vector: Dict[str, float] = {}
    dims = sentiment.get("emotion_dimensions")
    if isinstance(dims, dict) and dims:
        vector = {str(k).lower(): _safe_float(val, 0.0) for k, val in dims.items()}
        sources.append("emotion_dimensions_24")
    else:
        ev = sentiment.get("emotion_vector")
        if isinstance(ev, dict) and ev:
            vector = {str(k).lower(): _safe_float(val, 0.0) for k, val in ev.items()}
            sources.append("emotion_vector_10")

    dominant = str(sentiment.get("dominant_emotion") or "").lower().strip()
    if dominant and dominant != "neutral":
        vector.setdefault(dominant, max(vector.get(dominant, 0.0), 0.75))
        sources.append(f"dominant:{dominant}")

    if not vector:
        return gains, sources

    # 加權累積
    for island in ISLAND_IDS:
        affinity = _ISLAND_EMOTION_AFFINITY[island]
        acc = 0.0
        weight_sum = 0.0
        for label, strength in vector.items():
            s = _clamp(strength, 0.0, 1.0)
            if s <= 0.05:
                continue
            key = _LABEL_TO_AFFINITY_KEY.get(label, label)
            aff = affinity.get(key)
            if aff is None:
                continue
            acc += aff * s
            weight_sum += s
        if weight_sum > 0:
            gains[island] += (acc / weight_sum) * 0.35

    return gains, sources


def _normalize_gains(gains: Dict[str, float]) -> Dict[str, float]:
    cleaned = {
        k: max(0.0, float(gains.get(k, 0.0)))
        for k in ISLAND_IDS
    }
    total = sum(cleaned.values())
    if total <= 0:
        return {k: 0.25 for k in ISLAND_IDS}
    return {k: v / total for k, v in cleaned.items()}


def compute_island_gains(
    user_sentiment: Optional[Dict[str, Any]],
) -> IslandGainResult:
    """
    EmotionService（或相容 dict）→ 四島增益。
    回傳完整結構，不做截斷。
    """
    sentiment = user_sentiment if isinstance(user_sentiment, dict) else {}
    vad = normalize_vad(sentiment)
    sources = [f"vad:{vad.scale_detected}", f"polarity:{vad.polarity}"]

    gains = _base_gains_from_vad(vad)
    gains, label_sources = _gains_from_emotion_labels(sentiment, gains)
    sources.extend(label_sources)

    # 強度縮放（保留相對排序）
    intensity = max(0.15, vad.affect_intensity)
    gains = {k: max(0.01, v * (0.55 + 0.45 * intensity)) for k, v in gains.items()}
    gains = _normalize_gains(gains)
    primary = max(gains, key=gains.get)

    return IslandGainResult(
        gains=gains,
        primary_island=primary,
        vad=vad,
        sources=sources,
    )


def format_island_gains_guidance(result: IslandGainResult) -> str:
    """注入 SystemPrompt 的完整增益說明（Zero-Truncation）。"""
    g = result.gains
    v = result.vad
    lines = [
        "VAD → ISLAND GAINS (EmotionService bridge):",
        (
            f"- VAD signed: valence={v.valence_signed:.3f}, "
            f"arousal={v.arousal:.3f}, dominance={v.dominance_signed:.3f} "
            f"(scale={v.scale_detected}, polarity={v.polarity}, "
            f"intensity={v.affect_intensity:.3f})"
        ),
        (
            f"- Island gains: Mother={g.get('Mother', 0):.3f}, "
            f"Friend={g.get('Friend', 0):.3f}, "
            f"Empath={g.get('Empath', 0):.3f}, "
            f"Self={g.get('Self', 0):.3f}"
        ),
        f"- Gain-suggested primary: {result.primary_island}",
        f"- Sources: {', '.join(result.sources) if result.sources else 'vad_only'}",
    ]
    if v.dominant_emotion:
        lines.append(f"- Dominant emotion: {v.dominant_emotion}")
    if v.is_crisis_risk:
        lines.append("- Crisis risk flag: true (prefer Mother/Empath quiet presence)")
    return "\n".join(lines)
