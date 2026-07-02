# app/services/risk_assessment_service.py
"""
Turn-level clinical risk assessment for the main chat pipeline.
Combines keyword heuristics with EmotionService crisis signals.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class TurnRiskAssessment:
    """Single-turn risk assessment (1-5)."""
    risk_level: int
    suicidal_indicators: int = 0
    self_harm_indicators: int = 0
    hopelessness_indicators: int = 0
    isolation_indicators: int = 0
    crisis_keywords: List[str] = field(default_factory=list)
    confidence: float = 0.6
    sources: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


_CRISIS_KEYWORDS = {
    'suicidal': [
        '自殺', '死亡', '結束生命', '想死', '死咗好', '想唔駛活', '不想活', '尋死',
    ],
    'self_harm': [
        '自傷', '割', '傷自己', '砍自己', '痛自己',
    ],
    'hopelessness': [
        '無希望', '绝望', '絕望', '冇辦法', '唔掂', '完咗', '没有希望',
    ],
    'isolation': [
        '孤單', '孤立', '冇人', '冇朋友', '被拋棄', '孤独',
    ],
}


def _heuristic_risk(user_input: str) -> TurnRiskAssessment:
    """Keyword-based risk scoring (1-5)."""
    text = (user_input or "").lower()
    detected: List[str] = []
    scores = {'suicidal': 0, 'self_harm': 0, 'hopelessness': 0, 'isolation': 0}

    for category, keywords in _CRISIS_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                detected.append(keyword)
                scores[category] += 1

    total_score = sum(scores.values()) * 25

    if total_score >= 76:
        risk_level = 5
    elif total_score >= 51:
        risk_level = 4
    elif total_score >= 26:
        risk_level = 3
    elif total_score >= 11:
        risk_level = 2
    else:
        risk_level = 1

    return TurnRiskAssessment(
        risk_level=risk_level,
        suicidal_indicators=scores['suicidal'],
        self_harm_indicators=scores['self_harm'],
        hopelessness_indicators=scores['hopelessness'],
        isolation_indicators=scores['isolation'],
        crisis_keywords=detected,
        confidence=0.6 if detected else 0.5,
        sources=['heuristic_keywords'],
    )


def assess_turn_risk(
    user_input: str,
    emotion_profile: Dict[str, Any] | None = None,
) -> TurnRiskAssessment:
    """
    Assess risk for one user turn.

    Merges keyword heuristics with EmotionService crisis flags and VAD extremes.
    """
    assessment = _heuristic_risk(user_input)
    emotion_profile = emotion_profile or {}

    emotion_keywords = list(emotion_profile.get('detected_crisis_keywords') or [])
    if emotion_keywords:
        for kw in emotion_keywords:
            if kw not in assessment.crisis_keywords:
                assessment.crisis_keywords.append(kw)
        assessment.risk_level = max(assessment.risk_level, 4)
        assessment.sources.append('emotion_crisis_keywords')
        assessment.confidence = max(assessment.confidence, 0.85)

    if emotion_profile.get('is_crisis_risk'):
        assessment.risk_level = max(assessment.risk_level, 4)
        assessment.sources.append('emotion_is_crisis_risk')
        assessment.confidence = max(assessment.confidence, 0.9)

    valence = float(emotion_profile.get('valence', 0.0))
    arousal = float(emotion_profile.get('arousal', 0.0))
    if valence <= -0.6 and arousal >= 0.7:
        assessment.risk_level = max(assessment.risk_level, 3)
        assessment.sources.append('vad_extreme')

    return assessment
