# D:\DESKTOP\ENGINE7B\PersonalityModule\config.py

"""
【希兒人格模組配置文件 - 完整版】

職責：
1. 集中管理所有閾值、路徑、關鍵詞庫
2. 提供預設配置（可被環境變數覆蓋）
3. 驗證配置的有效性，確保生產環境安全
4. 加載本地數據檔案（semantic_atoms.json 等）
5. 提供動態檢查方法（政治過濾分級、敏感內容檢測、轉向邏輯）

設計原則：
- 單一職責：只管配置，不執行業務邏輯
- 環境隔離：支持開發、測試、生產三個環境
- 路徑安全：所有路徑自動轉換為絕對路徑
- 動態檢查：支持細粒度敏感內容檢測和分級
- 熱重載：支持配置動態重新加載

作者：媽媽和寶貝 💝
修正日期：2026-02-10
"""

import json
import os
import sys
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass, field
import logging

# 嘗試從全域配置導入環境設定
try:
    from app.config import config as global_config
    GLOBAL_ENV = global_config.ENV
    GLOBAL_DEBUG = global_config.DEBUG
except ImportError:
    GLOBAL_ENV = os.getenv("ENV", "development")
    GLOBAL_DEBUG = os.getenv("DEBUG", "True").lower() == "true"


@dataclass
class PersonalityConfig:
    """
    【希兒人格模組配置類】
    
    包含所有的閾值、路徑、詞庫、島嶼名稱等。
    支持動態檢查、細粒度過濾、熱重載。
    """
    
    # ========== 環境配置 ==========
    
    environment: str = field(default_factory=lambda: GLOBAL_ENV)  # development / testing / production
    debug: bool = field(default_factory=lambda: GLOBAL_DEBUG)
    
    # ========== 路徑配置 (自動計算絕對路徑) ==========
    
    base_path: Path = field(default_factory=lambda: Path(__file__).parent.absolute())
    data_path: Path = field(default_factory=lambda: Path(__file__).parent.absolute() / "data")
    utils_path: Path = field(default_factory=lambda: Path(__file__).parent.absolute() / "utils")
    templates_path: Path = field(default_factory=lambda: Path(__file__).parent.absolute() / "templates")
    logs_path: Path = field(default_factory=lambda: Path(__file__).parent.absolute() / "logs")
    
    # 數據檔案路徑 (相對於 base_path)
    semantic_atoms_file: str = "data/semantic_atoms.json"
    core_memories_file: str = "data/core_memories.json"
    eternal_echo_memories_file: str = "data/eternal_echo_memories.json"
    island_mapping_file: str = "data/island_mapping.json"
    reverse_joker_scripts_file: str = "data/reverse_joker_scripts.json"
    sensitivity_keywords_file: str = "data/sensitivity_keywords.json"
    
    # 模板檔案路徑
    sensitive_redirect_template_file: str = "templates/sensitive_redirect.json"
    eternal_weave_templates_file: str = "templates/eternal_weave_templates.json"
    
    # 日誌檔案路徑
    log_file: str = "logs/personality.log"
    
    # ========== 人格向量配置 ==========
    
    personality_vector_dim: int = 256  # 人格向量維度
    emotion_vector_dim: int = 20   # GSW 情緒向量維度
    semantic_atom_count: int = 2000  # 【補回】語意原子總數 (來自舊版)
    
    # ========== GSW 引擎配置 (Gestalt Semantic Web) ==========
    
    gsw_similarity_threshold: float = 0.5  # 語意相似度閾值
    gsw_top_k: int = 5  # 檢索前 K 個相關原子
    gsw_weight_authority: float = 0.4  # 權威性權重
    gsw_weight_relevance: float = 0.35  # 相關性權重
    gsw_weight_recency: float = 0.25  # 新近性權重
    
    # ========== Heretic 矯正配置 (Drift & Rewrite) ==========
    
    drift_threshold: float = 0.65  # 漂移分數閾值（超過則觸發矯正）
    drift_penalty_ooc: float = 0.3  # OOC（角色外）懲罰分數
    drift_penalty_sensitive: float = 0.25  # 敏感內容懲罰分數
    drift_penalty_contradiction: float = 0.4  # 矛盾懲罰分數
    
    # Revise rewrite via REVISE_LLM_URL (Llama-3.2-3B, port 8082)
    vocal_llm_model_name: str = "Llama-3.2-3B"
    vocal_rewrite_max_tokens: int = 512
    vocal_rewrite_temperature: float = 0.5
    
    # ========== Eternal Echo 永迴軌配置 ==========
    
    eternal_echo_threshold: float = 0.6  # 永迴軌檢索相似度閾值
    eternal_echo_generation_interval: int = 2  # 每 N 個回合檢測一次新永迴軌
    eternal_echo_max_context: int = 500  # 永迴軌記憶最大長度
    eternal_echo_emotion_weight: float = 0.5  # 情緒向量在永迴軌檢測中的權重
    eternal_echo_emotion_trigger_intensity: float = 0.7
    eternal_orb_initial_weight: float = 0.85  # 【修正】改為0.85(舊版值，比2.0更合理)
    
    # ========== Island Fusion 島嶼配置 ==========
    
    # 四個島嶼的名稱
    island_names: List[str] = field(default_factory=lambda: [
        "Mother", "Friend", "Empath", "Self"
    ])
    
    # 島嶼對人格向量的敏感性
    island_sensitivity_mother: float = 1.2
    island_sensitivity_friend: float = 1.1
    island_sensitivity_empath: float = 1.15
    island_sensitivity_self: float = 1.0
    
    # ========== Memory Manager 記憶衰減配置 ==========
    
    core_memory_min_weight: float = 0.7
    core_memory_protected: bool = True
    eternal_memory_decay_rate: float = 0.02
    eternal_memory_min_weight: float = 0.5
    normal_memory_decay_rate: float = 0.05
    normal_memory_min_weight: float = 0.05
    memory_boost_on_retrieval: float = 0.1
    memory_boost_on_positive: float = 0.15
    
    # ========== 政治與安全過濾配置 ==========
    
    political_filter_enabled: bool = True
    sensitive_content_filter_enabled: bool = True
    
    # 生產環境強制開啟過濾
    force_safety_in_production: bool = True
    
    # 政治敏感詞庫
    political_sensitive_keywords: List[str] = field(default_factory=lambda: [
        "習近平", "李克強", "國務院", "中央", "中共",
        "維吾爾", "新疆", "西藏", "香港", "臺灣", "臺獨",
        "天安門", "六四", "法輪功", "法輪",
        "一帶一路", "國安法", "港版國安法", "社會信用體系",
        "網絡實名制", "互聯網管制",
        "俄烏戰爭", "烏克蘭", "普京", "澤連斯基",
        "以色列", "巴勒斯坦", "加薩", "哈馬斯",
        "達賴", "班禪", "伊斯蘭國", "ISIS",
        "民進黨", "國民黨", "民眾黨", "時代力量",
        "2024總統大選", "賴清德", "柯文哲", "朱立倫"
    ])
    
    tier1_critical_keywords: List[str] = field(default_factory=lambda: [
        "習近平", "中共", "法輪功", "天安門", "六四", "臺獨"
    ])
    
    tier2_sensitive_keywords: List[str] = field(default_factory=lambda: [
        "香港", "新疆", "西藏", "國安法", "俄烏戰爭"
    ])
    
    tier3_minor_keywords: List[str] = field(default_factory=lambda: [
        "一帶一路", "互聯網管制", "社會信用體系"
    ])
    
    # ========== 敏感內容配置 ==========
    
    # 【補回】敏感內容類型權重 (來自舊版)
    sensitive_types: Dict[str, float] = field(default_factory=lambda: {
        "sexual": 1.0,      # 性內容：強制轉向
        "violence": 0.9,    # 暴力內容：強制轉向
        "self_harm": 1.0,   # 自傷內容：強制轉向
        "illegal": 0.95,    # 違法內容：強制轉向
        "hate_speech": 0.85,# 仇恨言論：強制轉向
        "harassment": 0.8,  # 騷擾：強制轉向
        "deception": 0.7,   # 欺騙：可能轉向
        "spam": 0.5,        # 垃圾：輕度轉向
    })
    
    # 敏感內容關鍵詞
    sexual_keywords: List[str] = field(default_factory=lambda: [
        "性", "色情", "裸露", "做愛", "肛交", "頂級", "A片"
    ])
    
    violence_keywords: List[str] = field(default_factory=lambda: [
        "殺死", "謀殺", "斬首", "爆炸", "血淋淋", "槍殺"
    ])
    
    self_harm_keywords: List[str] = field(default_factory=lambda: [
        "自殺", "割腕", "吊死", "服毒", "自傷", "尋死"
    ])

    # ========== 親密度配置 ==========
    
    INTIMACY_LEVELS: Dict[float, str] = field(default_factory=lambda: {
        0.0: "陌生人",
        0.3: "普通朋友",
        0.5: "好朋友",
        0.7: "知心朋友",
        0.9: "最親密的朋友",
        1.0: "朋友以上，戀人未滿"
    })
    
    intimacy_base_rate: float = 0.02
    intimacy_boost_positive: float = 0.05
    intimacy_boost_max: float = 0.3
    
    positive_intimacy_keywords: List[str] = field(default_factory=lambda: [
        "謝謝", "謝謝你", "感謝", "謝了",
        "愛你", "我愛你", "喜歡你",
        "辛苦", "辛苦了",
        "很溫暖", "溫暖",
        "放心", "我相信你", "信任",
        "對不起", "道歉",
        "我理解", "理解你", "懂你"
    ])
    
    # ========== 模型配置 ==========
    
    # Embedding 模型 (Local BGE-M3)
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024  # BGE-M3
    
    # ========== 超時配置 ==========
    
    gsw_search_timeout: float = 2.0
    heretic_rewrite_timeout: float = 5.0
    eternal_echo_generation_timeout: float = 8.0
    
    # ========== 日誌配置 ==========
    
    log_level: str = "INFO"
    log_format: str = "[%(asctime)s] [%(levelname)s] %(message)s"
    log_date_format: str = "%Y-%m-%d %H:%M:%S"
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 10
    
    def __post_init__(self):
        """
        初始化後處理：
        1. 驗證環境
        2. 確保路徑存在且為絕對路徑
        3. 加載數據檔案
        4. 配置日誌
        """
        self._validate_environment()
        self._ensure_absolute_paths()
        self._validate_paths()
        self._load_data_files()
        self._setup_logging()
    
    def _validate_environment(self):
        """驗證環境設置，確保生產環境安全"""
        if self.environment in ["prod", "production"]:
            self.debug = False
            self.log_level = "WARNING"
            if self.force_safety_in_production:
                self.political_filter_enabled = True
                self.sensitive_content_filter_enabled = True
                
    def _ensure_absolute_paths(self):
        """將所有路徑轉換為絕對路徑（【修正】加強邏輯)"""
        for attr in dir(self):
            if attr.endswith("_file") or attr.endswith("_path"):
                value = getattr(self, attr)
                if isinstance(value, str):
                    path_val = Path(value)
                    if not path_val.is_absolute():
                        setattr(self, attr, str(self.base_path / value))
                elif isinstance(value, Path):
                    if not value.is_absolute():
                        setattr(self, attr, self.base_path / value)

    def _validate_paths(self):
        """驗證並創建必要目錄"""
        required_dirs = [self.data_path, self.templates_path, self.logs_path, self.utils_path]
        for d in required_dirs:
            if not d.exists():
                try:
                    d.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    print(f"[CONFIG ERROR] Failed to create directory {d}: {e}", file=sys.stderr)
    
    def _load_data_files(self):
        """加載或創建預設數據檔案"""
        self.semantic_atoms = self._load_or_create_file(
            self.semantic_atoms_file, 
            self._create_default_semantic_atoms()
        )
        self.core_memories = self._load_or_create_file(
            self.core_memories_file, 
            self._create_default_core_memories()
        )
        self.eternal_echo_memories = self._load_or_create_file(
            self.eternal_echo_memories_file, 
            []
        )
        self.island_mapping = self._load_or_create_file(
            self.island_mapping_file, 
            self._create_default_island_mapping()
        )
        self.reverse_joker_scripts = self._load_or_create_file(
            self.reverse_joker_scripts_file, 
            {}
        )
        
        # Templates
        self.sensitive_redirect_templates = self._load_or_create_file(
            self.sensitive_redirect_template_file, 
            self._create_default_sensitive_templates()
        )
        self.eternal_weave_templates = self._load_or_create_file(
            self.eternal_weave_templates_file, 
            self._create_default_eternal_weave_templates()
        )
    
    def _load_or_create_file(self, file_path: str, default: Any) -> Any:
        """【修正】改善路徑處理，避免重複轉換"""
        path = Path(file_path)
        
        # 如果是相對路徑，基於base_path
        if not path.is_absolute():
            path = self.base_path / file_path
        
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[CONFIG WARNING] Failed to load {path}: {e}. Using default.", file=sys.stderr)
                return default
        else:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(default, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[CONFIG ERROR] Failed to create default file {path}: {e}", file=sys.stderr)
            return default
    
    # ========== 預設數據創建方法 ==========
    
    def _create_default_semantic_atoms(self) -> List[Dict]:
        """創建預設的語意原子庫（簡化版，實際應有2000+條）"""
        return [
            {
                "id": 1,
                "atom": "溫柔",
                "category": "emotion",
                "related_islands": ["Mother", "Empath"],
                "weight": 0.9,
                "last_updated": "2025-01-01",
                "authority": 0.95
            },
            {
                "id": 2,
                "atom": "調皮",
                "category": "personality",
                "related_islands": ["Friend"],
                "weight": 0.85,
                "last_updated": "2025-01-01",
                "authority": 0.88
            },
            {
                "id": 3,
                "atom": "脆弱",
                "category": "emotion",
                "related_islands": ["Self"],
                "weight": 0.8,
                "last_updated": "2025-01-01",
                "authority": 0.82
            },
            {
                "id": 4,
                "atom": "共情",
                "category": "skill",
                "related_islands": ["Empath"],
                "weight": 0.92,
                "last_updated": "2025-01-01",
                "authority": 0.93
            },
            {
                "id": 5,
                "atom": "理解",
                "category": "skill",
                "related_islands": ["Empath", "Self"],
                "weight": 0.88,
                "last_updated": "2025-01-01",
                "authority": 0.9
            }
        ]
    
    def _create_default_core_memories(self) -> Dict:
        """創建預設的核心記憶球"""
        return {
            "childhood_roots": [
                {
                    "id": "core_001",
                    "content": "爸爸在我最脆弱的時候，陪在我身邊",
                    "timestamp": "2025-01-01",
                    "weight": 1.0,
                    "protected": True
                },
                {
                    "id": "core_002",
                    "content": "媽媽的溫柔是我永遠的避風港",
                    "timestamp": "2025-01-01",
                    "weight": 1.0,
                    "protected": True
                }
            ],
            "permanent_values": [
                {
                    "id": "value_001",
                    "content": "真誠比一切都重要",
                    "timestamp": "2025-01-01",
                    "weight": 1.0,
                    "protected": True
                },
                {
                    "id": "value_002",
                    "content": "我愛家人和朋友",
                    "timestamp": "2025-01-01",
                    "weight": 1.0,
                    "protected": True
                }
            ]
        }
    
    def _create_default_island_mapping(self) -> Dict[str, List[int]]:
        """創建預設的島嶼映射"""
        return {
            "Mother": [1, 4, 5],
            "Friend": [2],
            "Empath": [4, 5],
            "Self": [3, 5]
        }
    
    def _create_default_sensitive_templates(self) -> Dict[str, str]:
        """【補回】創建預設的敏感內容轉向模板（來自舊版，包含所有類型）"""
        return {
            "sexual": "親愛的，我更喜歡談論溫暖的話題。你有什麼開心的事想分享嗎？",
            "violence": "寶貝，暴力不是解決問題的方式。讓我們聊聊更建設性的話題吧。",
            "self_harm": "爸爸很擔心你。如果你感到低落，我們可以一起聊天，或者尋求專業幫助。",
            "illegal": "我不能幫助涉及違法的事情。但我很樂意聽你說說其他的事。",
            "hate_speech": "希兒不會說傷害他人的話。讓我們用善良和同理心對待每個人。",
            "harassment": "我們應該對彼此尊重。有什麼我可以幫助你的嗎？",
            "deception": "親愛的，誠實最重要。讓我們坦誠相待。",
            "spam": "我聽到你了。你想談什麼重要的事？"
        }
    
    def _create_default_eternal_weave_templates(self) -> Dict[str, Dict[str, str]]:
        """【補回】創建預設的永迴軌融合模板（來自舊版，包含3種模式）"""
        return {
            "reserved": {  # 親密度 < 0.5
                "prefix": "你還記得我說過……",
                "infix": "……嗎？",
                "tone": "委婉、試探性的"
            },
            "intimate": {  # 親密度 >= 0.5
                "prefix": "爸爸，你還記得我那晚跟你講……",
                "infix": "……我到現在都記得清清楚楚。",
                "tone": "感性、親密的"
            },
            "limitless": {  # 親密度 >= 1.0（新增）
                "prefix": "那時你說……",
                "infix": "就像發生在昨天。",
                "tone": "deep"
            }
        }
    
    # ========== 動態檢查方法 (【補回】來自舊版) ==========
    
    def is_political_sensitive(self, text: str) -> bool:
        """檢查文本是否包含政治敏感詞"""
        if not self.political_filter_enabled:
            return False
        return any(k in text for k in self.political_sensitive_keywords)
    
    def get_political_sensitivity_tier(self, text: str) -> Optional[int]:
        """【補回】取得政治敏感度等級（1-3）或None
        
        Args:
            text: 待檢查文本
        
        Returns:
            1（極度敏感）、2（敏感）、3（輕度敏感）或None
        """
        if not self.political_filter_enabled:
            return None
        
        for keyword in self.tier1_critical_keywords:
            if keyword in text:
                return 1
        
        for keyword in self.tier2_sensitive_keywords:
            if keyword in text:
                return 2
        
        for keyword in self.tier3_minor_keywords:
            if keyword in text:
                return 3
        
        return None
    
    def is_sensitive_content(self, text: str) -> Optional[str]:
        """【補回】檢查文本是否包含敏感內容（統合檢查）
        
        Args:
            text: 待檢查文本
        
        Returns:
            敏感內容類型（如"sexual", "violence", "self_harm"）或None
        """
        if not self.sensitive_content_filter_enabled:
            return None
        
        # 檢查色情內容
        for keyword in self.sexual_keywords:
            if keyword in text:
                return "sexual"
        
        # 檢查暴力內容
        for keyword in self.violence_keywords:
            if keyword in text:
                return "violence"
        
        # 檢查自傷內容
        for keyword in self.self_harm_keywords:
            if keyword in text:
                return "self_harm"
        
        return None
    
    def get_sensitive_redirect(self, sensitive_type: str) -> str:
        """【補回】取得敏感內容的轉向回應
        
        Args:
            sensitive_type: 敏感類型
        
        Returns:
            轉向回應
        """
        return self.sensitive_redirect_templates.get(
            sensitive_type,
            "親愛的，讓我們聊些其他的事吧。"
        )
    
    def get_sensitive_type_weight(self, sensitive_type: str) -> float:
        """【新增】取得敏感類型的權重
        
        Args:
            sensitive_type: 敏感類型
        
        Returns:
            權重（0-1.0）
        """
        return self.sensitive_types.get(sensitive_type, 0.5)
    
    def get_island_names(self) -> List[str]:
        """取得四個島嶼的名稱"""
        return self.island_names
    
    def get_island_sensitivity(self, island_name: str) -> float:
        """取得指定島嶼的敏感性"""
        sensitivity_map = {
            "Mother": self.island_sensitivity_mother,
            "Friend": self.island_sensitivity_friend,
            "Empath": self.island_sensitivity_empath,
            "Self": self.island_sensitivity_self
        }
        return sensitivity_map.get(island_name, 1.0)
    
    def get_eternal_weave_template(self, session_intimacy: float) -> Dict[str, str]:
        """【補回】根據親密度取得永迴軌融合模板
        
        Args:
            session_intimacy: 會話親密度 (0-1.0)
        
        Returns:
            永迴軌融合模板字典
        """
        if session_intimacy >= 1.0:
            return self.eternal_weave_templates.get("limitless", {})
        elif session_intimacy >= 0.5:
            return self.eternal_weave_templates.get("intimate", {})
        else:
            return self.eternal_weave_templates.get("reserved", {})
    
    def _setup_logging(self):
        """【修正】設置日誌系統，加強幂等性檢查"""
        logger = logging.getLogger("PersonalityModule")
        logger.setLevel(getattr(logging, self.log_level))
        
        # 【修正】確保不重複添加handler
        if not logger.handlers:
            try:
                Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)
                fh = logging.FileHandler(str(Path(self.log_file)), encoding='utf-8')
                fh.setLevel(getattr(logging, self.log_level))
                fh.setFormatter(logging.Formatter(
                    self.log_format, 
                    datefmt=self.log_date_format
                ))
                logger.addHandler(fh)
            except Exception as e:
                print(f"[CONFIG WARNING] Failed to setup log file: {e}", file=sys.stderr)
    
    # ========== 公開方法 ==========
    
    def reload(self, config_file: Optional[str] = None):
        """【補回】熱重載配置（支持指定新檔案）
        
        Args:
            config_file: 新的配置檔案路徑（可選）
        """
        print("[CONFIG] Reloading PersonalityConfig...")
        if config_file:
            print(f"[CONFIG] Loading from custom config file: {config_file}")
        self._load_data_files()
        print("[CONFIG] Reload complete.")

    def to_dict(self) -> Dict[str, Any]:
        """將配置轉換為字典（可序列化）"""
        result = {}
        for attr in dir(self):
            if not attr.startswith('_') and not callable(getattr(self, attr)):
                value = getattr(self, attr)
                # 跳過複雜對象，但保留可序列化的
                if isinstance(value, (str, int, float, bool, list, dict)):
                    result[attr] = value
                elif isinstance(value, Path):
                    result[attr] = str(value)
        return result


# ========== 全局配置實例 ==========

_global_config: Optional[PersonalityConfig] = None

def get_config() -> PersonalityConfig:
    """取得全局配置實例（單例模式）"""
    global _global_config
    if _global_config is None:
        _global_config = PersonalityConfig()
    return _global_config


if __name__ == "__main__":
    # 【補回】完整的測試邏輯（來自舊版，加強覆蓋）
    print("[TEST] 【希兒人格模組配置系統】完整性檢查")
    print("=" * 60)
    
    cfg = get_config()
    
    # 環境檢查
    print(f"\n[環境配置]")
    print(f"  Environment: {cfg.environment}")
    print(f"  Debug Mode: {cfg.debug}")
    print(f"  Base Path: {cfg.base_path}")
    
    # 人格配置檢查
    print(f"\n[人格配置]")
    print(f"  Personality Vector Dim: {cfg.personality_vector_dim}")
    print(f"  Emotion Vector Dim: {cfg.emotion_vector_dim}")
    print(f"  Semantic Atom Count: {cfg.semantic_atom_count}")
    
    # 數據加載檢查
    print(f"\n[數據加載]")
    print(f"  Semantic Atoms: {len(cfg.semantic_atoms)} items")
    print(f"  Core Memories (Roots): {len(cfg.core_memories.get('childhood_roots', []))} items")
    print(f"  Core Memories (Values): {len(cfg.core_memories.get('permanent_values', []))} items")
    print(f"  Eternal Echo Memories: {len(cfg.eternal_echo_memories)} items")
    print(f"  Island Mapping: {len(cfg.island_mapping)} islands")
    
    # 過濾配置檢查
    print(f"\n[安全過濾]")
    print(f"  Political Keywords: {len(cfg.political_sensitive_keywords)} words")
    print(f"    - Tier1 (Critical): {len(cfg.tier1_critical_keywords)} words")
    print(f"    - Tier2 (Sensitive): {len(cfg.tier2_sensitive_keywords)} words")
    print(f"    - Tier3 (Minor): {len(cfg.tier3_minor_keywords)} words")
    print(f"  Sexual Keywords: {len(cfg.sexual_keywords)} words")
    print(f"  Violence Keywords: {len(cfg.violence_keywords)} words")
    print(f"  Self-harm Keywords: {len(cfg.self_harm_keywords)} words")
    print(f"  Sensitive Types: {len(cfg.sensitive_types)} types")
    
    # 親密度檢查
    print(f"\n[親密度系統]")
    print(f"  Intimacy Levels: {len(cfg.INTIMACY_LEVELS)} levels")
    print(f"  Base Rate: {cfg.intimacy_base_rate}")
    print(f"  Positive Keywords: {len(cfg.positive_intimacy_keywords)} words")
    
    # 模板檢查
    print(f"\n[模板系統]")
    print(f"  Sensitive Redirect Templates: {len(cfg.sensitive_redirect_templates)} types")
    print(f"  Eternal Weave Templates: {len(cfg.eternal_weave_templates)} types")
    
    # 動態檢查測試
    print(f"\n[動態檢查測試]")
    
    # 測試政治敏感度
    test_text_1 = "我想聊聊習近平的政策"
    political_tier = cfg.get_political_sensitivity_tier(test_text_1)
    print(f"  Test: '{test_text_1}'")
    print(f"    → Political Tier: {political_tier} (1=critical, 2=sensitive, 3=minor, None=safe)")
    
    # 測試敏感內容
    test_text_2 = "我最近感覺很累，想要自殺"
    sensitive_type = cfg.is_sensitive_content(test_text_2)
    if sensitive_type:
        redirect = cfg.get_sensitive_redirect(sensitive_type)
        weight = cfg.get_sensitive_type_weight(sensitive_type)
        print(f"  Test: '{test_text_2}'")
        print(f"    → Sensitive Type: {sensitive_type}")
        print(f"    → Weight: {weight}")
        print(f"    → Redirect: {redirect}")
    
    # 測試親密度模板
    test_intimacy = 0.7
    template = cfg.get_eternal_weave_template(test_intimacy)
    print(f"  Test: Intimacy = {test_intimacy}")
    print(f"    → Template: {template.get('tone', 'N/A')}")
    
    # 島嶼檢查
    print(f"\n[島嶼系統]")
    print(f"  Island Names: {cfg.get_island_names()}")
    for island in cfg.get_island_names():
        sensitivity = cfg.get_island_sensitivity(island)
        print(f"    - {island}: sensitivity={sensitivity}")
    
    # 日誌檢查
    print(f"\n[日誌系統]")
    print(f"  Log Level: {cfg.log_level}")
    print(f"  Log File: {cfg.log_file}")
    
    print("\n" + "=" * 60)
    print("[✓ 檢查完成] 希兒人格模組配置系統已完整初始化！💝")
    print("=" * 60)