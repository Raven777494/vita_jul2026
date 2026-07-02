# app/utils/language_switcher.py
import re
import logging
from dataclasses import dataclass
from typing import Optional, Literal
from app.config import Config
import redis
from redis.exceptions import RedisError
from app.models import UserLanguagePreference

logger = logging.getLogger(__name__)

LangCode = Literal["yue-Hant", "zh-Hans", "en", "ja"]

@dataclass
class SwitchResult:
    effective_lang: LangCode
    mixed_style: bool
    message_to_user: Optional[str]
    persisted: bool

class LanguageSwitcher:
    # Redis 鍵的前綴
    REDIS_PREFIX = "user:lang_pref:"
    REDIS_TTL = 86400 * 30  # 30 天過期時間
    
    def __init__(self, redis_client: redis.Redis = None, db_session = None):
        """
        Args:
            redis_client: Redis 連接實例
            db_session: SQLAlchemy session（可選，用於備份）
        """
        self.redis = redis_client
        self.db = db_session
        
        # 高頻詞彙特徵
        self.VOCAB_JA = {"の", "に", "は", "を", "が", "て", "で", "と", "し", "れ", "私", "僕", "何", "はい", "です", "ます"}
        self.VOCAB_ZH = {"的", "了", "是", "我", "你", "他", "在", "有", "个", "这", "那", "么", "很", "什", "么", "呢"}
        self.VOCAB_HK = {"嘅", "咗", "冇", "喺", "啱", "嗰", "唔", "系", "睇", "佢", "嚟", "噶", "嘢", "乜", "點", "仲"}

    def get_user_pref(self, user_id: str) -> Optional[LangCode]:
        """讀取用戶語言偏好（優先 Redis，降級到 DB）"""
        try:
            if self.redis:
                lang = self.redis.get(f"{self.REDIS_PREFIX}{user_id}")
                if lang:
                    return lang
            
            # 降級到數據庫（如果 Redis 不可用）
            if self.db:
                return self._get_from_db(user_id)
                
        except RedisError as e:
            logger.warning(f"Redis read failed for user {user_id}: {e}")
            if self.db:
                return self._get_from_db(user_id)
        
        return None

    def set_user_pref(self, user_id: str, lang: LangCode):
        """設置用戶語言偏好（Redis 主儲存 + DB 備份）"""
        # 1. 主儲存：Redis（非阻塞）
        if self.redis:
            try:
                self.redis.setex(
                    f"{self.REDIS_PREFIX}{user_id}",
                    self.REDIS_TTL,
                    lang
                )
            except RedisError as e:
                logger.error(f"Redis write failed for user {user_id}: {e}")
        
        # 2. 備份：DB（可選，使用異步任務避免阻塞）
        if self.db:
            try:
                self._set_to_db_async(user_id, lang)
            except Exception as e:
                logger.error(f"DB backup failed for user {user_id}: {e}")

    def _get_from_db(self, user_id: str) -> Optional[LangCode]:
        """從數據庫讀取（降級方案）"""
        try:
            from app.models import UserLanguagePreference
            pref = self.db.query(UserLanguagePreference).filter_by(user_id=user_id).first()
            return pref.language if pref else None
        except Exception as e:
            logger.error(f"DB read failed: {e}")
            return None

    def _set_to_db_async(self, user_id: str, lang: LangCode):
        """異步更新數據庫備份（不阻塞主流程）"""
        # 這裡可以使用 Celery/任務隊列
        from app.models import UserLanguagePreference
        try:
            pref = self.db.query(UserLanguagePreference).filter_by(user_id=user_id).first()
            if pref:
                pref.language = lang
            else:
                pref = UserLanguagePreference(user_id=user_id, language=lang)
                self.db.add(pref)
            self.db.commit()
        except Exception as e:
            logger.error(f"DB write failed: {e}")
            self.db.rollback()

    def _detect_lang(self, text: str) -> LangCode:
        """檢測輸入文本的語言"""
        t = text.strip()
        if not t:
            return "yue-Hant"
        
        # 1. 日文（最強特徵：平假名/片假名）
        if re.search(r"[ぁ-んァ-ン]", t):
            return "ja"
        
        # 2. 詞彙計數
        chars = set(t)
        score_hk = len(chars.intersection(self.VOCAB_HK))
        score_zh = len(chars.intersection(self.VOCAB_ZH))
        
        # 3. 決策
        if score_hk > 0:
            return "yue-Hant"
        if score_zh > 0:
            return "zh-Hans"
        
        # 4. 英文/其他
        ascii_count = sum(1 for c in t if c.isascii())
        if len(t) > 0 and (ascii_count / len(t)) > 0.85:
            return "en"
        
        # 全漢字但無特徵 -> 簡中
        if re.search(r"[\u4e00-\u9fff]", t):
            return "zh-Hans"
        
        return "yue-Hant"

    def decide(self, user_id: str, user_text: str) -> SwitchResult:
        """決定回應語言"""
        # 1. 偵測本句語言
        detected = self._detect_lang(user_text)
        
        # 2. 讀取用戶長期偏好
        pref = self.get_user_pref(user_id)
        
        # 3. 即時適應模式（Instant Adapt）
        effective_lang = detected
        
        # 如果偵測到默認粵語，但用戶有其他偏好，則用偏好
        if detected == "yue-Hant" and pref:
            effective_lang = pref
        
        # 如果偵測到外語，更新偏好並切換
        if detected != "yue-Hant" and detected != pref:
            self.set_user_pref(user_id, detected)
        
        return SwitchResult(
            effective_lang=effective_lang,
            mixed_style=(effective_lang == "yue-Hant"),
            message_to_user=None,
            persisted=True
        )