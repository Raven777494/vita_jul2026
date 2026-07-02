"""24-dimension emotion vector helpers (Phase 5)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

EMOTION_LABELS_24: List[str] = [
    "joy",
    "sadness",
    "fear",
    "anger",
    "surprise",
    "disgust",
    "trust",
    "anticipation",
    "hope",
    "despair",
    "love",
    "hate",
    "pride",
    "humility",
    "desire",
    "loneliness",
    "anxiety",
    "calm",
    "shame",
    "guilt",
    "relief",
    "frustration",
    "contentment",
    "excitement",
]

# Map legacy 10-label keys to 24-label keys where names differ.
_LEGACY_10_TO_24 = {
    "joy": "joy",
    "sad": "sadness",
    "hope": "hope",
    "fear": "fear",
    "despair": "despair",
    "desire": "desire",
    "pride": "pride",
    "humility": "humility",
    "love": "love",
    "hate": "hate",
}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def expand_emotion_dimensions_24(
    vad: Dict[str, float],
    emotions_10: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Expand VAD + optional 10-dim profile into a normalized 24-dim vector.
    """
    vad = vad or {}
    valence = float(vad.get("valence", 0.0))
    arousal = float(vad.get("arousal", 0.5))
    dominance = float(vad.get("dominance", 0.0))

    emotions: Dict[str, float] = {label: 0.35 for label in EMOTION_LABELS_24}

    if emotions_10:
        for key, val in emotions_10.items():
            mapped = _LEGACY_10_TO_24.get(str(key).lower(), str(key).lower())
            if mapped in emotions:
                emotions[mapped] = _clamp(val)

    # VAD-derived adjustments (fill dimensions not covered by legacy 10-label set).
    if valence > 0.2:
        emotions["joy"] = _clamp(emotions["joy"] + valence * 0.35)
        emotions["contentment"] = _clamp(0.4 + valence * 0.45)
        emotions["love"] = _clamp(emotions["love"] + valence * 0.25)
        emotions["relief"] = _clamp(0.35 + valence * 0.3)
    elif valence < -0.2:
        neg = abs(valence)
        emotions["sadness"] = _clamp(emotions["sadness"] + neg * 0.35)
        emotions["despair"] = _clamp(emotions["despair"] + neg * 0.3)
        emotions["frustration"] = _clamp(0.35 + neg * 0.35)

    if arousal > 0.55:
        emotions["excitement"] = _clamp(0.35 + arousal * 0.45)
        emotions["anxiety"] = _clamp(emotions["anxiety"] + (arousal - 0.5) * 0.35)
        emotions["anger"] = _clamp(emotions["anger"] + (arousal - 0.5) * 0.25)
        emotions["surprise"] = _clamp(emotions["surprise"] + (arousal - 0.5) * 0.2)
    else:
        emotions["calm"] = _clamp(0.45 + (0.55 - arousal) * 0.4)

    if dominance > 0.2:
        emotions["pride"] = _clamp(emotions["pride"] + dominance * 0.25)
        emotions["trust"] = _clamp(emotions["trust"] + dominance * 0.2)
    elif dominance < -0.2:
        emotions["shame"] = _clamp(0.35 + abs(dominance) * 0.35)
        emotions["humility"] = _clamp(emotions["humility"] + abs(dominance) * 0.2)
        emotions["loneliness"] = _clamp(emotions["loneliness"] + abs(dominance) * 0.25)

    emotions["anticipation"] = _clamp(0.35 + max(0.0, valence) * 0.2 + arousal * 0.15)
    emotions["disgust"] = _clamp(emotions["disgust"] + max(0.0, -valence) * 0.15)

    if emotions.get("sadness", 0) > 0.55 and dominance < 0:
        emotions["guilt"] = _clamp(0.4 + emotions["sadness"] * 0.25)

    return {label: round(_clamp(emotions.get(label, 0.35)), 4) for label in EMOTION_LABELS_24}


def emotion_dimension_count() -> int:
    return len(EMOTION_LABELS_24)
