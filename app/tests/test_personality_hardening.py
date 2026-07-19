from PersonalityModule.heretic_coordinator import HereticCoordinator
from PersonalityModule.personality_module import PersonalityModule
from PersonalityModule.political_filter import PoliticalFilter


def test_mother_guidance_low_intimacy_is_not_over_intimate():
    coordinator = HereticCoordinator(config={})
    text = coordinator._inject_island_guidance("你已經講得好清楚。", "Mother", intimacy=0.2)

    assert text.startswith("我聽住你講，")
    assert "寶貝" not in text
    assert "媽媽" not in text


def test_mother_guidance_high_intimacy_uses_presence_not_role_play():
    coordinator = HereticCoordinator(config={})
    text = coordinator._inject_island_guidance("你唔需要一個人捱。", "Mother", intimacy=0.95)

    assert text.startswith("我會喺度陪你，")
    assert "寶貝" not in text
    assert "媽媽" not in text


def test_autobiography_conflict_filters_noncanonical_memory():
    module = PersonalityModule(config={"data_dir": "./PersonalityModule/data"})

    conflict_text = "我爸爸以前成日帶我去某城市。"
    safe_text = "你上次提到工作壓力好大。"

    assert module._is_autobiography_conflict(conflict_text, {"id": "echo_123"}) is True
    assert module._is_autobiography_conflict(conflict_text, {"id": "memory_01"}) is False
    assert module._is_autobiography_conflict(conflict_text, {"id": "core_001"}) is False
    assert module._is_autobiography_conflict(
        conflict_text,
        {"id": "x", "metadata": {"memory_type": "canonical"}},
    ) is False
    assert module._is_autobiography_conflict(safe_text, {"id": "echo_123"}) is False


def test_sanitize_memory_context_removes_conflicting_lines_and_limits_output():
    module = PersonalityModule(
        config={
            "data_dir": "./PersonalityModule/data",
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 30,
        }
    )
    context = "\n".join(
        [
            "- 我爸爸以前住喺其他地方。",
            "- 你上次話夜晚會焦慮。",
            "- 你今日比之前穩定咗。",
            "- 這是一段很長很長的內容" + ("A" * 200),
        ]
    )

    sanitized = module._sanitize_memory_context(context)

    assert "我爸爸" not in sanitized
    assert len(sanitized.splitlines()) <= 1
    assert "…" in sanitized or len(sanitized) <= 40


def test_political_filter_fails_safe_on_detector_error(monkeypatch):
    filt = PoliticalFilter(config={}, data_dir="./PersonalityModule/data")

    def boom(*_args, **_kwargs):
        raise RuntimeError("detector broken")

    monkeypatch.setattr(filt, "_check_text", boom)
    result = filt.detect_sensitivity("普通對話", "普通對話")

    assert result["is_sensitive"] is True
    assert result["risk_level"] == "tier2"
    assert result["recommendation"] == "rewrite"
    assert result.get("source") == "detector_error"
