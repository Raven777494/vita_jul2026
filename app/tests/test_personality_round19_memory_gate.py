"""
Round 19: 回憶注入閘門（更新）
- 每輪最多 1 段
- Zero-Truncation：預設不裁切正文
- crisis／high 跳過趣事／鬧向記憶（不依賴音量分數）
"""

from pathlib import Path

from PersonalityModule.personality_module import PersonalityModule

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def _module() -> PersonalityModule:
    return PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )


def test_format_memory_enforces_one_snippet_zero_truncation():
    module = _module()
    long_body = "你上次話夜晚會焦慮，又話想有人陪，仲講咗好多細節。" + ("細" * 40)
    memories = [
        {"id": "echo_a", "content": long_body},
        {"id": "echo_b", "content": "你今日比之前穩定咗。"},
    ]

    text = module._format_memory_context(memories, intensity="medium")
    lines = [ln for ln in text.splitlines() if ln.strip()]

    assert len(lines) == 1
    body = lines[0][2:].strip() if lines[0].startswith("- ") else lines[0]
    assert body == long_body
    assert "…" not in body
    assert "你今日比之前穩定咗" not in text


def test_crisis_gate_skips_anecdote_memory_and_keeps_safe():
    module = _module()
    memories = [
        {
            "id": "echo_fun",
            "content": "你講過個好笑嘅趣事，大家笑死。",
            "metadata": {"expression": "anecdote"},
        },
        {
            "id": "echo_safe",
            "content": "你話而家好攰，想有人陪。",
        },
    ]

    text = module._format_memory_context(memories, intensity="crisis")

    assert "趣事" not in text
    assert "笑死" not in text
    assert "好攰" in text
    assert len([ln for ln in text.splitlines() if ln.strip()]) == 1


def test_high_gate_skips_playful_and_anecdote_only_memories():
    module = _module()
    memories = [
        {
            "id": "echo_play",
            "content": "我哋成日打鬧開玩笑。",
            "metadata": {"tone": "playful"},
        },
    ]

    text = module._format_memory_context(memories, intensity="high")
    assert text == ""


def test_sanitize_memory_context_applies_crisis_anecdote_gate():
    module = _module()
    context = "\n".join(
        [
            "- 你講過一個開心事同趣事。",
            "- 你上次話夜晚會焦慮。",
            "- 這是一段很長很長的內容" + ("B" * 200),
        ]
    )

    sanitized = module._sanitize_memory_context(context, intensity="crisis")

    assert "趣事" not in sanitized
    assert "開心事" not in sanitized
    assert "焦慮" in sanitized
    lines = [ln for ln in sanitized.splitlines() if ln.strip()]
    assert len(lines) == 1


def test_prepare_draft_guidance_memory_gate_on_crisis():
    module = _module()
    module.setup_dependencies({})

    guidance = module.prepare_draft_guidance(
        user_input="我好絕望，真係想死",
        session_state={"intimacy": 0.1, "turn_count": 1},
        turn_info={
            "user_sentiment": {"valence": 0.05, "arousal": 0.95},
            "risk_level": 4,
            "memory_context": (
                "- 你講過個好笑趣事。\n"
                "- 你上次話夜晚會焦慮。"
            ),
        },
    )

    assert guidance["intensity"] == "crisis"
    mc = guidance.get("memory_context") or ""
    assert "好笑趣事" not in mc
    assert "你講過個好笑" not in mc
    if "相關記憶:" in guidance["system_prompt"]:
        injected = guidance["system_prompt"].split("相關記憶:", 1)[1]
        assert "好笑趣事" not in injected
        assert "你講過個好笑" not in injected
    if mc:
        assert len([ln for ln in mc.splitlines() if ln.strip()]) <= 1
        assert "焦慮" in mc


def test_medium_allows_anecdote_without_budget_scores():
    """音量表拆除後：medium 不再靠 anecdote=0 擋；只靠 intensity。"""
    module = _module()
    memories = [
        {
            "id": "echo_fun",
            "content": "記得嗰個趣事嗎？",
            "metadata": {"expression_type": "anecdote"},
        },
        {
            "id": "echo_ok",
            "content": "你話想慢慢講。",
        },
    ]
    text = module._format_memory_context(memories, intensity="medium")
    assert "趣事" in text
    assert len([ln for ln in text.splitlines() if ln.strip()]) == 1
