# app/models.py
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base
from datetime import datetime
from app.schemas import LanguageCode

Base = declarative_base()

class UserLanguagePreference(Base):
    """用戶語言偏好 - 資料庫表格模型"""
    __tablename__ = "user_language_preferences"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(100), unique=True, nullable=False, index=True)
    primary_language = Column(String(20), nullable=False)  # 使用 LanguageCode 的值
    secondary_language = Column(String(20), nullable=True)
    code_mixing_preference = Column(String(20), default="casual")
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f"<UserLangPref(user_id={self.user_id}, lang={self.primary_language})>"