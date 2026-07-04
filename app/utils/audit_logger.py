# app/utils/audit_logger.py
# 加密審計日誌系統 – 隱私保護、臨床合規

import json
import hashlib
import logging
from typing import Dict, Any, Optional, TYPE_CHECKING
from datetime import datetime
import base64

from app.config import config
from app.logger import get_audit_logger, get_critical_logger

if TYPE_CHECKING:
    from cryptography.fernet import Fernet

audit_logger = get_audit_logger('audit_events')
critical_logger = get_critical_logger('critical_events')

class AuditLogger:
    """
    審計日誌記錄器
    
    職責：
    1. 記錄所有用戶交互（加密）
    2. 分層加密（某些欄位完全隱藏，某些欄位可解密）
    3. 合規記錄（臨床隱私保護）
    """
    
    def __init__(self):
        """初始化加密"""
        self.cipher_suite = self._init_cipher()
    
    def _init_cipher(self) -> Optional["Fernet"]:
        """
        初始化加密套件
        
        使用 Fernet（AES-128 CBC + HMAC）對稱加密
        """
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            logging.warning(
                "[AUDIT] cryptography package not installed; audit field encryption disabled"
            )
            return None

        try:
            # 金鑰必須是 32 位 base64 編碼
            if isinstance(config.ENCRYPT_KEY, str):
                # 確保金鑰是有效的 base64
                key_bytes = config.ENCRYPT_KEY.encode()
                
                # 如果不是有效的 base64，進行轉換
                if len(key_bytes) != 44:  # Fernet 金鑰是 44 位 base64
                    # 使用 SHA-256 生成確定性的金鑰
                    hash_obj = hashlib.sha256(key_bytes)
                    key_bytes = base64.urlsafe_b64encode(hash_obj.digest())
                
                return Fernet(key_bytes)
            
            else:
                logging.warning("[AUDIT] 加密金鑰無效，禁用加密")
                return None
        
        except Exception as e:
            logging.error(f"[AUDIT] 加密初始化失敗: {e}")
            return None
    
    def _encrypt_field(self, value: str) -> str:
        """
        加密單個欄位
        
        Args:
            value: 待加密值
        
        Returns:
            str: 加密後的值（base64）
        """
        if not self.cipher_suite or not value:
            return "[ENCRYPTED]"
        
        try:
            encrypted = self.cipher_suite.encrypt(value.encode())
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logging.error(f"[AUDIT] 加密失敗: {e}")
            return "[ENCRYPTION_ERROR]"
    
    def _decrypt_field(self, encrypted_value: str) -> Optional[str]:
        """
        解密單個欄位（僅授權用戶）
        
        Args:
            encrypted_value: 加密值
        
        Returns:
            str: 解密後的值，失敗返回 None
        """
        if not self.cipher_suite or encrypted_value.startswith('['):
            return None
        
        try:
            encrypted = base64.b64decode(encrypted_value.encode())
            decrypted = self.cipher_suite.decrypt(encrypted)
            return decrypted.decode()
        except Exception as e:
            logging.error(f"[AUDIT] 解密失敗: {e}")
            return None
    
    def _hash_pii(self, value: str) -> str:
        """
        對個人身份信息進行單向 Hash
        
        Args:
            value: 待 Hash 值
        
        Returns:
            str: SHA-256 Hash（16 進制）
        """
        return hashlib.sha256(value.encode()).hexdigest()
    
    def log_user_input(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str,
        user_input: str,
        turn_number: int,
        risk_flags: Optional[Dict[str, Any]] = None
    ):
        """
        記錄用戶輸入（敏感 – 加密）
        
        加密策略：
        - user_id: SHA-256（不可逆）
        - user_input: Fernet（可解密，僅授權）
        - risk_flags: 匿名化（e.g. "suicidal" → "high_risk_1"）
        
        Args:
            user_id: 用戶 ID
            session_id: 會話 ID
            conversation_id: 對話 ID
            user_input: 用戶輸入文本
            turn_number: 對話輪數
            risk_flags: 風險標籤字典
        """
        audit_entry = {
            'event_type': 'user_input',
            'timestamp': datetime.now().isoformat(),
            'user_id_hash': self._hash_pii(user_id),  # 不可逆
            'session_id': session_id,
            'conversation_id': conversation_id,
            'turn_number': turn_number,
            'user_input_encrypted': self._encrypt_field(user_input),  # 可解密
            'input_length': len(user_input),  # 元數據
            'risk_flags_anonymized': self._anonymize_risk_flags(risk_flags or {})
        }
        
        audit_logger.info(json.dumps(audit_entry, ensure_ascii=False))
    
    def log_system_response(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str,
        response_text: str,
        turn_number: int,
        model_used: str,
        confidence: float = 0.0
    ):
        """
        記錄系統回應（低敏感 – 隱藏文本）
        
        加密策略：
        - response_text: 完全隱藏（只記錄長度、類型）
        - response_type: 記錄（empathy/support/directive）
        
        Args:
            user_id: 用戶 ID
            session_id: 會話 ID
            conversation_id: 對話 ID
            response_text: 回應文本
            turn_number: 對話輪數
            model_used: 使用的模型
            confidence: 信心分數
        """
        audit_entry = {
            'event_type': 'system_response',
            'timestamp': datetime.now().isoformat(),
            'user_id_hash': self._hash_pii(user_id),
            'session_id': session_id,
            'conversation_id': conversation_id,
            'turn_number': turn_number,
            'response_length': len(response_text),
            'response_type': self._classify_response(response_text),
            'model_used': model_used,
            'confidence': round(confidence, 3),
            'response_text': '[HIDDEN]'  # 完全隱藏
        }
        
        audit_logger.info(json.dumps(audit_entry, ensure_ascii=False))
    
    def log_risk_assessment(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str,
        risk_level: int,
        walker_score: float,
        risk_keywords: list,
        turn_number: int
    ):
        """
        記錄風險評估（臨床敏感）
        
        Args:
            user_id: 用戶 ID
            session_id: 會話 ID
            conversation_id: 對話 ID
            risk_level: 風險級別（1-5）
            walker_score: 陪伴分數（0.0-1.0）
            risk_keywords: 檢測到的風險關鍵詞
            turn_number: 對話輪數
        """
        audit_entry = {
            'event_type': 'risk_assessment',
            'timestamp': datetime.now().isoformat(),
            'user_id_hash': self._hash_pii(user_id),
            'session_id': session_id,
            'conversation_id': conversation_id,
            'turn_number': turn_number,
            'risk_level': risk_level,
            'walker_score': round(walker_score, 3),
            'risk_keywords_count': len(risk_keywords),
            'risk_keywords_hash': self._hash_pii(json.dumps(risk_keywords))
        }
        
        # 高風險使用 critical logger
        if risk_level >= 4:
            critical_logger.warning(json.dumps(audit_entry, ensure_ascii=False))
        else:
            audit_logger.info(json.dumps(audit_entry, ensure_ascii=False))
    
    def log_escalation(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str,
        risk_level: int,
        escalation_reason: str,
        escalated_to: str,
        turn_number: int
    ):
        """
        記錄危機升級事件（最高優先級）
        
        Args:
            user_id: 用戶 ID
            session_id: 會話 ID
            conversation_id: 對話 ID
            risk_level: 風險級別
            escalation_reason: 升級原因
            escalated_to: 升級對象
            turn_number: 對話輪數
        """
        escalation_entry = {
            'event_type': 'risk_escalation',
            'timestamp': datetime.now().isoformat(),
            'user_id_hash': self._hash_pii(user_id),
            'session_id': session_id,
            'conversation_id': conversation_id,
            'turn_number': turn_number,
            'risk_level': risk_level,
            'escalation_reason': escalation_reason,
            'escalated_to': escalated_to
        }
        
        critical_logger.critical(json.dumps(escalation_entry, ensure_ascii=False))

    def log_prompt_injection_attempt(
        self,
        user_id: str,
        session_id: str,
        patterns_detected: list,
        input_length: int,
        was_modified: bool,
    ) -> None:
        """Log prompt injection detection metadata (no user content).

        Written to audit.log only. Do not include raw user text — VictoriaLogs
        must not receive adversarial payloads from this event.
        """
        audit_entry = {
            "event_type": "prompt_injection_attempt",
            "timestamp": datetime.now().isoformat(),
            "user_id_hash": self._hash_pii(user_id) if user_id else "",
            "session_id": session_id,
            "patterns_detected": list(patterns_detected),
            "input_length": int(input_length),
            "was_modified": bool(was_modified),
        }
        audit_logger.info(json.dumps(audit_entry, ensure_ascii=False))
    
    def log_system_error(
        self,
        user_id: str,
        session_id: str,
        error_type: str,
        error_message: str,
        model_failed: Optional[str] = None,
        turn_number: int = 0
    ):
        """
        記錄系統錯誤
        
        Args:
            user_id: 用戶 ID
            session_id: 會話 ID
            error_type: 錯誤類型（timeout/llm_error/db_error）
            error_message: 錯誤訊息
            model_failed: 失敗的模型
            turn_number: 對話輪數
        """
        error_entry = {
            'event_type': 'system_error',
            'timestamp': datetime.now().isoformat(),
            'user_id_hash': self._hash_pii(user_id),
            'session_id': session_id,
            'error_type': error_type,
            'error_message': error_message,
            'model_failed': model_failed,
            'turn_number': turn_number
        }
        
        critical_logger.error(json.dumps(error_entry, ensure_ascii=False))
    
    # ============ 輔助方法 ============
    
    def _anonymize_risk_flags(self, risk_flags: Dict) -> Dict:
        """
        匿名化風險標籤
        
        例如：{"suicidal": 1, "self_harm": 1} → {"high_risk_1": 1, "high_risk_2": 1}
        """
        anonymized = {}
        flag_counter = 1
        
        for flag, value in risk_flags.items():
            if value > 0:
                anonymized[f"high_risk_{flag_counter}"] = value
                flag_counter += 1
        
        return anonymized
    
    def _classify_response(self, response_text: str) -> str:
        """
        分類回應類型
        
        Returns:
            str: empathy / support / directive / safety_alert
        """
        if not response_text:
            return 'empty'
        
        lower_text = response_text.lower()
        
        # 簡單啟發式分類
        if any(keyword in lower_text for keyword in ['聽到', '理解', '明白', '感受']):
            return 'empathy'
        elif any(keyword in lower_text for keyword in ['幫忙', '支持', '陪你']):
            return 'support'
        elif any(keyword in lower_text for keyword in ['試下', '可以', '建議']):
            return 'directive'
        elif any(keyword in lower_text for keyword in ['一起', '這一刻', '慢慢', '安穩', '呼吸']):
            return 'companion_grounding'
        else:
            return 'other'

# 全局審計日誌實例
audit_log = AuditLogger()