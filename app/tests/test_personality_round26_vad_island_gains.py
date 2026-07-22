"""
Round 26 / P6.1 — EmotionService VAD → 四島增益
- signed valence (-1..1) 不再被誤讀成 unit 0..1
- EmotionService 中性 0.0 不應被判成負向
- 危機 VAD 抬 Mother/Empath
- 正向 VAD 抬 Friend/Self
- prepare_draft_guidance 完整暴露 island_gains / vad_normalized（Zero-Truncation）
"""

from pathlib import Path

from PersonalityModule.island_fusion import IslandFusion
from PersonalityModule.persona_graph import PersonaGraph
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.vad_bridge import (
    compute_island_gains,
    detect_vad_scale,
    normalize_vad,
)

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def test_p61_emotion_service_neutral_zero_is_signed_not_negative():
    """EmotionService 中性 valence=0.0 必須辨識為 signed，極性 neutral。"""
    sentiment = {
        "valence": 0.0,
        "arousal": 0.5,
        "dominance": 0.0,
        "dominant_emotion": "neutral",
        "method": "heuristic",
        "vad_scale": "signed",
    }
    assert detect_vad_scale(sentiment) == "signed"
    vad = normalize_vad(sentiment)
    assert vad.polarity == "neutral"
    assert abs(vad.valence_signed) < 1e-9
    assert abs(vad.valence_unit - 0.5) < 1e-9


def test_p61_legacy_unit_half_stays_neutral():
    sentiment = {"valence": 0.5, "arousal": 0.3, "vad_scale": "unit"}
    vad = normalize_vad(sentiment)
    assert vad.scale_detected == "unit"
    assert vad.polarity == "neutral"
    assert abs(vad.valence_signed) < 1e-9


def test_p61_crisis_vad_boosts_mother_empath():
    sentiment = {
        "valence": -0.85,
        "arousal": 0.92,
        "dominance": -0.6,
        "dominant_emotion": "despair",
        "is_crisis_risk": True,
        "method": "heuristic",
        "vad_scale": "signed",
        "emotion_vector": {"despair": 0.9, "sad": 0.8, "fear": 0.7},
    }
    result = compute_island_gains(sentiment)
    assert result.gains["Empath"] > result.gains["Friend"]
    assert result.gains["Mother"] > result.gains["Self"]
    assert result.primary_island in {"Mother", "Empath"}
    assert result.vad.polarity == "negative"


def test_p61_positive_vad_boosts_friend_self():
    sentiment = {
        "valence": 0.75,
        "arousal": 0.4,
        "dominance": 0.3,
        "dominant_emotion": "joy",
        "method": "api",
        "vad_scale": "signed",
        "emotion_vector": {"joy": 0.85, "hope": 0.6},
    }
    result = compute_island_gains(sentiment)
    assert result.gains["Friend"] > result.gains["Mother"]
    assert result.gains["Self"] >= result.gains["Empath"] * 0.85
    assert result.primary_island in {"Friend", "Self"}


def test_p61_island_fusion_uses_vad_bridge_not_unit_bug():
    fusion = IslandFusion(data_dir=DATA_PATH)
    # 舊 bug：valence=0.0 被當成 <=0.35 → 全面負向放大
    neutral = fusion._calculate_emotion_affinity(
        {
            "valence": 0.0,
            "arousal": 0.5,
            "method": "heuristic",
            "vad_scale": "signed",
            "dominant_emotion": "neutral",
        }
    )
    crisis = fusion._calculate_emotion_affinity(
        {
            "valence": -0.8,
            "arousal": 0.9,
            "method": "heuristic",
            "vad_scale": "signed",
            "dominant_emotion": "despair",
            "is_crisis_risk": True,
        }
    )
    assert crisis["Empath"] > neutral["Empath"]
    assert crisis["Mother"] > neutral["Friend"]


def test_p61_persona_graph_intensity_follows_signed_crisis_thresholds():
    graph = PersonaGraph(config={"data_path": DATA_PATH})
    resolution = graph.resolve(
        user_input="我而家好亂",
        intimacy=0.2,
        user_sentiment={
            "valence": -0.75,
            "arousal": 0.8,
            "dominance": -0.5,
            "is_crisis_risk": True,
            "dominant_emotion": "despair",
            "method": "heuristic",
            "vad_scale": "signed",
        },
        risk_level=2,
    )
    assert resolution.intensity == "crisis"
    assert resolution.island_gains
    assert resolution.vad_normalized.get("valence_signed", 0) < -0.5
    assert "VAD → ISLAND GAINS" in resolution.prompt_fragment
    assert "Island gains (VAD bridge):" in resolution.prompt_fragment


def test_p61_prepare_draft_guidance_exposes_full_gains_zero_truncation():
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )
    module.setup_dependencies({})
    guidance = module.prepare_draft_guidance(
        user_input="今日好開心想傾下計",
        session_state={"intimacy": 0.2, "turn_count": 1},
        turn_info={
            "user_sentiment": {
                "valence": 0.7,
                "arousal": 0.35,
                "dominance": 0.2,
                "dominant_emotion": "joy",
                "method": "heuristic",
                "vad_scale": "signed",
            },
            "risk_level": 0,
        },
    )
    assert guidance["prompt_contract"] == "pre_draft_full_no_truncation"
    assert isinstance(guidance.get("island_gains"), dict)
    assert set(guidance["island_gains"]) >= {"Mother", "Friend", "Empath", "Self"}
    assert isinstance(guidance.get("vad_normalized"), dict)
    assert "valence_signed" in guidance["vad_normalized"]
    prompt = guidance["system_prompt"]
    assert "VAD → ISLAND GAINS" in prompt
    # Zero-Truncation：增益數字完整出現在 prompt
    for island, value in guidance["island_gains"].items():
        assert f"{island}=" in prompt
        assert f"{value:.3f}" in prompt


def test_p61_activation_negative_high_arousal_prefers_care_islands():
    fusion = IslandFusion(data_dir=DATA_PATH)
    activation, primary = fusion.calculate_activation(
        response_vector=[],
        user_sentiment={
            "valence": -0.7,
            "arousal": 0.85,
            "dominance": -0.4,
            "dominant_emotion": "sad",
            "method": "api",
            "vad_scale": "signed",
            "emotion_dimensions": {
                "sadness": 0.9,
                "fear": 0.7,
                "despair": 0.8,
                "loneliness": 0.75,
            },
        },
        conversation_context="我好難受好驚",
        extracted_info={},
        session_state={"intimacy": 0.2},
    )
    assert primary in {"Mother", "Empath"}
    assert activation["Empath"] + activation["Mother"] > activation["Friend"] + activation["Self"]
