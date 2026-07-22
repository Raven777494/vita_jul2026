# PersonalityModule/memory_retrieval.py
# P6.3 — Canon／Echo 檢索統一 API（介面與可觀測性收斂）

"""
雙庫（seele_childhood_canon + core_memories）已能在過去話題下選最多 1 段正史。
Echo／GSW 為另一層會話回響。

本模組不合併實體 JSON，只統一：
1. 回傳結構（MemoryBundle）
2. 觀測 trace（為何選／為何跳過）
3. draft／anchor 共用入口

Zero-Truncation：MemoryItem.content 保持完整，不做硬截斷。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

MEMORY_RETRIEVAL_VERSION = "1.0.0"

LAYER_SOUL_CANON = "soul_canon"
LAYER_SOUL_CORE = "soul_core"
LAYER_ECHO = "echo"
LAYER_OTHER = "other"

SOUL_SKIP_NO_PAST = "no_past_topic"
SOUL_SKIP_NO_HIT = "past_triggered_but_no_viable_candidate"
SOUL_SKIP_EMPTY_INPUT = "empty_user_input"
SOUL_OK = "selected"


@dataclass
class MemoryItem:
    memory_id: str
    layer: str
    source: str
    content: str
    score: float = 0.0
    title: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryTrace:
    past_topic_triggered: bool = False
    soul_selected: bool = False
    soul_skip_reason: str = ""
    soul_candidates_scored: int = 0
    soul_best_score: float = 0.0
    soul_memory_id: str = ""
    soul_source: str = ""
    echo_requested_k: int = 0
    echo_returned: int = 0
    echo_filtered: int = 0
    echo_ids: List[str] = field(default_factory=list)
    restrict_memory: bool = False
    notes: List[str] = field(default_factory=list)
    version: str = MEMORY_RETRIEVAL_VERSION

    def to_public_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryBundle:
    soul: Optional[MemoryItem] = None
    echoes: List[MemoryItem] = field(default_factory=list)
    trace: MemoryTrace = field(default_factory=MemoryTrace)
    version: str = MEMORY_RETRIEVAL_VERSION
    # 內部契約：完整 raw dict（供 conflict_repair／guidance）；不經 public 序列化整包
    soul_raw: Optional[Dict[str, Any]] = None
    echo_raw: List[Dict[str, Any]] = field(default_factory=list)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "soul": self.soul.to_public_dict() if self.soul else None,
            "echoes": [e.to_public_dict() for e in self.echoes],
            "trace": self.trace.to_public_dict(),
            "soul_memory_id": self.trace.soul_memory_id,
            "soul_source": self.trace.soul_source,
            "echo_ids": list(self.trace.echo_ids),
            "echo_count": len(self.echoes),
            "past_topic_triggered": self.trace.past_topic_triggered,
            "soul_selected": self.trace.soul_selected,
            "soul_skip_reason": self.trace.soul_skip_reason,
        }


def _safe_str(value: Any) -> str:
    return "" if value is None else str(value)


def classify_soul_layer(source: str) -> str:
    src = (source or "").strip().lower()
    if src in {"seele_childhood_canon", "canonical", "canon"}:
        return LAYER_SOUL_CANON
    if src in {"core_memories", "core", "gray_orbs", "gold_orbs"}:
        return LAYER_SOUL_CORE
    return LAYER_SOUL_CORE if src.startswith("core") else LAYER_SOUL_CANON


def classify_echo_layer(memory: Dict[str, Any]) -> str:
    if not isinstance(memory, dict):
        return LAYER_OTHER
    memory_type = _safe_str(memory.get("memory_type") or "").lower()
    source = _safe_str(memory.get("source") or "").lower()
    memory_id = _safe_str(memory.get("id") or memory.get("memory_id") or "").lower()
    if (
        memory_type in {"eternal_echo", "echo"}
        or source in {"eternal_echo", "echo"}
        or memory_id.startswith("echo_")
    ):
        return LAYER_ECHO
    if source in {"seele_childhood_canon", "core_memories", "canonical", "core"}:
        # 不應出現在 echo 列表；若誤入仍標 other 以便觀測
        return LAYER_OTHER
    return LAYER_ECHO if "echo" in source or "echo" in memory_type else LAYER_OTHER


def soul_dict_to_item(memory: Optional[Dict[str, Any]]) -> Optional[MemoryItem]:
    if not isinstance(memory, dict):
        return None
    content = _safe_str(memory.get("content") or "").strip()
    if not content:
        return None
    source = _safe_str(memory.get("source") or "")
    memory_id = _safe_str(memory.get("memory_id") or memory.get("id") or "")
    try:
        score = float(memory.get("retrieval_score", memory.get("score", 0.0)) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    meta = {
        k: memory.get(k)
        for k in (
            "lesson",
            "tendency",
            "repair_path",
            "companion_line",
            "trigger",
            "trigger_keywords",
            "island_affinity",
            "weight",
            "weight_norm",
            "tier",
            "orb_bucket",
            "year",
            "age",
        )
        if k in memory
    }
    return MemoryItem(
        memory_id=memory_id,
        layer=classify_soul_layer(source),
        source=source,
        content=content,
        score=score,
        title=_safe_str(memory.get("title") or "").strip(),
        metadata=meta,
    )


def echo_dict_to_item(memory: Dict[str, Any]) -> Optional[MemoryItem]:
    if not isinstance(memory, dict):
        return None
    content = _safe_str(
        memory.get("content") or memory.get("response") or memory.get("text") or ""
    ).strip()
    if not content:
        return None
    memory_id = _safe_str(memory.get("id") or memory.get("memory_id") or "")
    source = _safe_str(memory.get("source") or memory.get("memory_type") or "echo")
    try:
        score = float(
            memory.get("similarity", memory.get("score", memory.get("echo_score", 0.0)))
            or 0.0
        )
    except (TypeError, ValueError):
        score = 0.0
    return MemoryItem(
        memory_id=memory_id,
        layer=classify_echo_layer(memory),
        source=source,
        content=content,
        score=score,
        title=_safe_str(memory.get("title") or "").strip(),
        metadata={
            "memory_type": memory.get("memory_type"),
            "similarity": memory.get("similarity"),
            "raw_keys": sorted(str(k) for k in memory.keys()),
        },
    )


class MemoryRetrievalAPI:
    """
    Canon／Echo 統一檢索門面。

    PersonalityModule 透過本類組裝 MemoryBundle；
    選路規則仍由 host 的 _select_soul_memory／GSW／meta 控制執行。
    """

    def __init__(self, host: Any = None):
        self.host = host
        self.version = MEMORY_RETRIEVAL_VERSION

    def assemble_bundle(
        self,
        *,
        soul_raw: Optional[Dict[str, Any]] = None,
        echo_raw: Optional[Sequence[Dict[str, Any]]] = None,
        past_topic_triggered: bool = False,
        soul_skip_reason: str = "",
        soul_candidates_scored: int = 0,
        soul_best_score: float = 0.0,
        echo_requested_k: int = 0,
        echo_filtered: int = 0,
        restrict_memory: bool = False,
        notes: Optional[List[str]] = None,
    ) -> MemoryBundle:
        soul_item = soul_dict_to_item(soul_raw)
        echoes: List[MemoryItem] = []
        kept_raw: List[Dict[str, Any]] = []
        for mem in echo_raw or []:
            if not isinstance(mem, dict):
                continue
            item = echo_dict_to_item(mem)
            if item is None:
                continue
            # 防呆：不可變正史 id 不得混入 echo 層輸出
            if self.host and hasattr(self.host, "is_immutable_soul_memory_id"):
                if self.host.is_immutable_soul_memory_id(item.memory_id):
                    echo_filtered += 1
                    continue
            echoes.append(item)
            kept_raw.append(mem)

        skip = soul_skip_reason
        if soul_item is None and not skip:
            skip = SOUL_SKIP_NO_HIT if past_topic_triggered else SOUL_SKIP_NO_PAST

        trace = MemoryTrace(
            past_topic_triggered=bool(past_topic_triggered),
            soul_selected=soul_item is not None,
            soul_skip_reason="" if soul_item is not None else skip,
            soul_candidates_scored=int(soul_candidates_scored),
            soul_best_score=float(soul_best_score or 0.0),
            soul_memory_id=soul_item.memory_id if soul_item else "",
            soul_source=soul_item.source if soul_item else "",
            echo_requested_k=int(echo_requested_k or 0),
            echo_returned=len(echoes),
            echo_filtered=int(echo_filtered or 0),
            echo_ids=[e.memory_id for e in echoes if e.memory_id],
            restrict_memory=bool(restrict_memory),
            notes=list(notes or []),
        )
        return MemoryBundle(
            soul=soul_item,
            echoes=echoes,
            trace=trace,
            soul_raw=soul_raw if isinstance(soul_raw, dict) else None,
            echo_raw=kept_raw,
        )

    def retrieve_soul_for_draft(
        self,
        user_input: str,
        *,
        primary_island: str = "Empath",
        intensity: str = "medium",
    ) -> Tuple[Optional[Dict[str, Any]], MemoryTrace]:
        """
        Draft 前置：雙庫最多 1 段正史。
        回傳 (raw_soul_dict|None, partial_trace)。
        """
        host = self.host
        text = user_input or ""
        notes: List[str] = []
        if not text.strip():
            bundle = self.assemble_bundle(
                past_topic_triggered=False,
                soul_skip_reason=SOUL_SKIP_EMPTY_INPUT,
                notes=["empty_user_input"],
            )
            return None, bundle.trace

        past = False
        if host and hasattr(host, "_is_past_or_childhood_topic"):
            past = bool(host._is_past_or_childhood_topic(text))
        else:
            past = any(
                tok in text
                for tok in ("以前", "細個", "童年", "舊時", "讀書時", "屋企")
            )

        if not past:
            bundle = self.assemble_bundle(
                past_topic_triggered=False,
                soul_skip_reason=SOUL_SKIP_NO_PAST,
                notes=["soul_gate:require_past_topic"],
            )
            return None, bundle.trace

        candidates_scored = 0
        if host and hasattr(host, "_iter_soul_memory_candidates"):
            try:
                candidates_scored = len(host._iter_soul_memory_candidates() or [])
            except Exception:
                candidates_scored = 0

        selected = None
        if host and hasattr(host, "_select_soul_memory"):
            selected = host._select_soul_memory(
                text,
                primary_island=primary_island,
                intensity=intensity,
            )
        best_score = 0.0
        if isinstance(selected, dict):
            try:
                best_score = float(selected.get("retrieval_score") or 0.0)
            except (TypeError, ValueError):
                best_score = 0.0
            notes.append("soul_selected_via_dual_lib")
        else:
            notes.append("past_triggered_no_selection")

        bundle = self.assemble_bundle(
            soul_raw=selected if isinstance(selected, dict) else None,
            past_topic_triggered=True,
            soul_skip_reason="" if selected else SOUL_SKIP_NO_HIT,
            soul_candidates_scored=candidates_scored,
            soul_best_score=best_score,
            notes=notes,
        )
        return (selected if isinstance(selected, dict) else None), bundle.trace

    def normalize_echoes_for_context(
        self,
        memories: Optional[Sequence[Any]],
        *,
        intensity: str = "medium",
        max_items: Optional[int] = None,
        restrict_memory: bool = False,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        將 GSW／預載 echo 列表正規化為可注入上下文的 raw dict 列表 + 觀測。
        預設每輪最多 1 段（與 PersonalityConfig max_memory_snippet_per_turn 對齊）。
        """
        host = self.host
        raw_list = [m for m in (memories or []) if isinstance(m, dict)]
        requested = len(raw_list)

        limit = max_items
        if limit is None and host and hasattr(host, "_get_memory_snippet_limits"):
            try:
                limit, _chars = host._get_memory_snippet_limits()
            except Exception:
                limit = 1
        if limit is None:
            limit = 1
        try:
            limit = max(0, int(limit))
        except (TypeError, ValueError):
            limit = 1

        kept: List[Dict[str, Any]] = []
        filtered = 0
        for mem in raw_list:
            if limit >= 0 and len(kept) >= limit:
                break
            content = _safe_str(mem.get("content") or mem.get("response") or "")
            if not content.strip():
                filtered += 1
                continue
            mem_id = mem.get("id") or mem.get("memory_id")
            if host and hasattr(host, "is_immutable_soul_memory_id"):
                if host.is_immutable_soul_memory_id(mem_id):
                    filtered += 1
                    continue
            if host and hasattr(host, "_is_autobiography_conflict"):
                try:
                    if host._is_autobiography_conflict(content, mem):
                        filtered += 1
                        continue
                except Exception:
                    pass
            if host and hasattr(host, "_should_skip_memory_for_expression_gate"):
                try:
                    if host._should_skip_memory_for_expression_gate(
                        content, mem, intensity=intensity
                    ):
                        filtered += 1
                        continue
                except Exception:
                    pass
            if restrict_memory and host and hasattr(host, "_is_core_or_echo_memory"):
                # 寬鬆：若 host 無此方法則保留
                pass
            kept.append(mem)

        obs = {
            "echo_input": requested,
            "echo_kept": len(kept),
            "echo_filtered": filtered,
            "echo_limit": limit,
            "restrict_memory": bool(restrict_memory),
            "echo_ids": [
                _safe_str(m.get("id") or m.get("memory_id") or "")
                for m in kept
            ],
        }
        return kept, obs

    def retrieve_for_draft(
        self,
        user_input: str,
        *,
        primary_island: str = "Empath",
        intensity: str = "medium",
        retrieved_memories: Optional[Sequence[Any]] = None,
        memory_context: str = "",
        restrict_memory: bool = False,
        echo_requested_k: int = 0,
    ) -> MemoryBundle:
        """
        prepare_draft_guidance 用：soul(0|1) + 正規化 echo 觀測。
        """
        soul_raw, soul_trace = self.retrieve_soul_for_draft(
            user_input,
            primary_island=primary_island,
            intensity=intensity,
        )
        echo_raw, echo_obs = self.normalize_echoes_for_context(
            retrieved_memories,
            intensity=intensity,
            restrict_memory=restrict_memory,
        )
        notes = list(soul_trace.notes)
        if memory_context and not echo_raw:
            notes.append("memory_context_string_present_without_structured_echoes")
        if echo_obs.get("echo_filtered"):
            notes.append(f"echo_filtered={echo_obs['echo_filtered']}")

        return self.assemble_bundle(
            soul_raw=soul_raw,
            echo_raw=echo_raw,
            past_topic_triggered=soul_trace.past_topic_triggered,
            soul_skip_reason=soul_trace.soul_skip_reason,
            soul_candidates_scored=soul_trace.soul_candidates_scored,
            soul_best_score=soul_trace.soul_best_score,
            echo_requested_k=int(echo_requested_k or echo_obs.get("echo_input") or 0),
            echo_filtered=int(echo_obs.get("echo_filtered") or 0),
            restrict_memory=restrict_memory,
            notes=notes,
        )

    async def retrieve_for_turn(
        self,
        user_input: str,
        *,
        primary_island: str = "Empath",
        intensity: str = "medium",
        user_embedding: Optional[List[float]] = None,
        user_id: Optional[str] = None,
        preloaded_memories: Optional[Sequence[Any]] = None,
        meta_control: Optional[Dict[str, Any]] = None,
    ) -> MemoryBundle:
        """
        Anchor／回合級：soul + meta 控制後的 echo 檢索。
        """
        host = self.host
        meta = meta_control if isinstance(meta_control, dict) else {}
        restrict = bool(meta.get("restrict_memory", False))
        try:
            top_k = int(meta.get("gsw_top_k", 4) or 4)
        except (TypeError, ValueError):
            top_k = 4
        top_k = max(1, min(20, top_k))

        soul_raw, soul_trace = self.retrieve_soul_for_draft(
            user_input,
            primary_island=primary_island,
            intensity=intensity,
        )

        echoes_raw: List[Dict[str, Any]] = []
        if isinstance(preloaded_memories, list) and preloaded_memories:
            echoes_raw = [m for m in preloaded_memories if isinstance(m, dict)]
        elif host and hasattr(host, "_apply_meta_memory_controls"):
            try:
                controlled = await host._apply_meta_memory_controls(
                    user_embedding=user_embedding or [],
                    user_id=user_id,
                    preloaded_memories=None,
                    meta_control=meta,
                )
                if isinstance(controlled, list):
                    echoes_raw = [m for m in controlled if isinstance(m, dict)]
            except Exception as exc:
                soul_trace.notes.append(f"echo_search_failed:{exc}")

        kept, echo_obs = self.normalize_echoes_for_context(
            echoes_raw,
            intensity=intensity,
            restrict_memory=restrict,
        )
        notes = list(soul_trace.notes) + [
            f"echo_meta_top_k={top_k}",
            f"echo_kept={echo_obs.get('echo_kept')}",
        ]
        return self.assemble_bundle(
            soul_raw=soul_raw,
            echo_raw=kept,
            past_topic_triggered=soul_trace.past_topic_triggered,
            soul_skip_reason=soul_trace.soul_skip_reason,
            soul_candidates_scored=soul_trace.soul_candidates_scored,
            soul_best_score=soul_trace.soul_best_score,
            echo_requested_k=top_k,
            echo_filtered=int(echo_obs.get("echo_filtered") or 0),
            restrict_memory=restrict,
            notes=notes,
        )
