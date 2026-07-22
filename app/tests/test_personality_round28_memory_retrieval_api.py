"""
Round 28 / P6.3 — Canon／Echo 檢索統一 API
- MemoryRetrievalAPI 組裝 MemoryBundle + 完整 trace
- prepare_draft_guidance 暴露 memory_bundle（可觀測）
- 過去話題最多 1 段正史；非過去話題 skip 可解釋
- Zero-Truncation：soul content 完整進入 guidance／bundle
- 不二次選路：bundle.soul_raw 與 guidance.soul_memory 一致
"""

from __future__ import annotations

from pathlib import Path

from PersonalityModule.memory_retrieval import (
    MEMORY_RETRIEVAL_VERSION,
    MemoryRetrievalAPI,
    SOUL_SKIP_NO_PAST,
)
from PersonalityModule.personality_module import PersonalityModule

DATA_PATH = str(Path(__file__).resolve().parents[2] / "PersonalityModule" / "data")


def _module() -> PersonalityModule:
    module = PersonalityModule(
        config={
            "data_dir": DATA_PATH,
            "data_path": DATA_PATH,
            "max_memory_snippet_per_turn": 1,
            "max_memory_snippet_chars": 0,
        }
    )
    module.setup_dependencies({})
    return module


def test_p63_memory_retrieval_api_wired_on_setup():
    module = _module()
    assert module.memory_retrieval is not None
    assert isinstance(module.memory_retrieval, MemoryRetrievalAPI)
    assert module.memory_retrieval.host is module
    assert module.memory_retrieval.version == MEMORY_RETRIEVAL_VERSION


def test_p63_bundle_skips_soul_without_past_topic():
    module = _module()
    bundle = module.memory_retrieval.retrieve_for_draft(
        "今日天氣幾好，想食麵",
        primary_island="Friend",
        intensity="medium",
        retrieved_memories=[
            {
                "id": "echo_demo_1",
                "source": "eternal_echo",
                "memory_type": "eternal_echo",
                "content": "上次你話想靜啲。",
            }
        ],
        echo_requested_k=1,
    )
    public = bundle.to_public_dict()
    assert public["past_topic_triggered"] is False
    assert public["soul_selected"] is False
    assert public["soul"] is None
    assert public["soul_skip_reason"] == SOUL_SKIP_NO_PAST
    assert public["echo_count"] == 1
    assert "echo_demo_1" in public["echo_ids"]
    assert public["version"] == MEMORY_RETRIEVAL_VERSION


def test_p63_bundle_selects_at_most_one_soul_on_past_topic():
    module = _module()
    bundle = module.memory_retrieval.retrieve_for_draft(
        "講起童年同以前屋企，風扇聲",
        primary_island="Mother",
        intensity="medium",
    )
    public = bundle.to_public_dict()
    assert public["past_topic_triggered"] is True
    assert public["soul_selected"] is True
    assert public["soul"] is not None
    assert public["soul_memory_id"]
    assert public["soul_source"] in {"seele_childhood_canon", "core_memories"}
    assert public["soul_skip_reason"] == ""
    content = public["soul"]["content"]
    assert isinstance(content, str) and content.strip()
    # Zero-Truncation：bundle 內容與 raw 一致且完整
    assert isinstance(bundle.soul_raw, dict)
    assert bundle.soul_raw.get("content") == content
    assert len(content) == len(str(bundle.soul_raw.get("content") or ""))


def test_p63_prepare_draft_exposes_memory_bundle_and_matches_soul_raw():
    module = _module()
    guidance = module.prepare_draft_guidance(
        user_input="我想講下童年以前嘅事，細個時屋企點樣",
        session_state={"intimacy": 0.2, "turn_count": 2},
        turn_info={
            "user_sentiment": {"valence": 0.5, "arousal": 0.4, "vad_scale": "signed"},
            "risk_level": 0,
            "retrieved_memories": [
                {
                    "id": "echo_keep",
                    "source": "eternal_echo",
                    "content": "你上次提過想有人陪。",
                },
                {
                    "id": "echo_extra",
                    "source": "eternal_echo",
                    "content": "多餘第二段不應注入（max=1）。",
                },
            ],
        },
    )
    mb = guidance.get("memory_bundle") or {}
    assert isinstance(mb, dict)
    assert mb.get("version") == MEMORY_RETRIEVAL_VERSION
    assert mb.get("past_topic_triggered") is True
    assert mb.get("soul_selected") is True
    assert guidance.get("soul_memory_id") == mb.get("soul_memory_id")
    assert guidance.get("soul_memory_source") == mb.get("soul_source")
    soul = guidance.get("soul_memory")
    assert isinstance(soul, dict)
    assert soul.get("memory_id") or soul.get("id")
    assert str(soul.get("content") or "") in guidance["system_prompt"]
    # 最多 1 段正史標題
    assert guidance["system_prompt"].count("SOUL MEMORY") == 1
    # echo 正規化上限 1
    assert mb.get("echo_count") == 1
    assert mb.get("echo_ids") == ["echo_keep"]


def test_p63_prepare_draft_no_past_records_skip_reason():
    module = _module()
    guidance = module.prepare_draft_guidance(
        user_input="我而家好攰",
        session_state={"intimacy": 0.1, "turn_count": 1},
        turn_info={"user_sentiment": {"valence": -0.2, "arousal": 0.3}, "risk_level": 0},
    )
    mb = guidance.get("memory_bundle") or {}
    assert mb.get("past_topic_triggered") is False
    assert mb.get("soul_selected") is False
    assert mb.get("soul_skip_reason") == SOUL_SKIP_NO_PAST
    assert not guidance.get("soul_memory")


def test_p63_filters_immutable_soul_id_from_echo_layer():
    module = _module()
    # 取一個真實正史 id（若有）
    candidates = module._iter_soul_memory_candidates()
    soul_id = ""
    if candidates:
        soul_id = str(
            candidates[0].get("memory_id") or candidates[0].get("id") or ""
        )
    if not soul_id:
        soul_id = "seele_canon_placeholder_id"
        module.is_immutable_soul_memory_id = lambda mid: str(mid) == soul_id  # type: ignore

    kept, obs = module.memory_retrieval.normalize_echoes_for_context(
        [
            {
                "id": soul_id,
                "source": "eternal_echo",
                "content": "不應以 echo 身份注入正史。",
            },
            {
                "id": "echo_ok",
                "source": "eternal_echo",
                "content": "呢段先係回響。",
            },
        ],
        intensity="medium",
    )
    assert len(kept) == 1
    assert kept[0]["id"] == "echo_ok"
    assert obs["echo_filtered"] >= 1


def test_p63_public_dict_omits_soul_raw_object():
    module = _module()
    bundle = module.memory_retrieval.retrieve_for_draft(
        "以前細個讀書時屋企",
        primary_island="Self",
        intensity="medium",
    )
    public = bundle.to_public_dict()
    assert "soul_raw" not in public
    assert "echo_raw" not in public
    if bundle.soul is not None:
        assert "content" in public["soul"]
        assert public["soul"]["content"] == bundle.soul_raw.get("content")
