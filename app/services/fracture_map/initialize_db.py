# D:\DESKTOP\ENGINE7B\app\services\fracture_map\initialize_db.py
# 希兒個人化裂痕地圖資料庫初始化程式

import sqlite3
from pathlib import Path
import logging
from datetime import datetime

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 資料庫路徑
DB_PATH = Path("D:/DESKTOP/ENGINE7B/app/services/fracture_map/fracture_map.db")

def create_database():
    """建立 fracture_map.db 並初始化所有表"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        logger.info(f"正在建立資料庫：{DB_PATH}")
        
        # 表1：user_fracture_points（用戶專屬裂痕點）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_fracture_points (
                user_id TEXT NOT NULL,
                trigger_keyword TEXT NOT NULL,
                context_tags TEXT,                          -- JSON 字符串
                emotion_spike_score REAL,
                comfort_efficiency REAL DEFAULT 0.5,
                last_triggered DATETIME,
                decay_rate REAL DEFAULT 0.08,
                trigger_count INTEGER DEFAULT 1,
                is_active BOOLEAN DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, trigger_keyword)
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_fracture ON user_fracture_points(user_id, is_active)')
        
        # 表2：user_safe_anchors（用戶專屬安全島）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_safe_anchors (
                user_id TEXT NOT NULL,
                anchor_type TEXT NOT NULL,                  -- topic, activity, memory, object, phrase
                content TEXT NOT NULL,
                effectiveness_score REAL DEFAULT 0.5,
                usage_count INTEGER DEFAULT 0,
                last_used DATETIME,
                island_association TEXT,                    -- JSON
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, anchor_type, content)
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_safe_anchor_user ON user_safe_anchors(user_id, anchor_type)')
        
        # 表3：crisis_events（危機事件記錄）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS crisis_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                trigger_type TEXT,
                arousal_score REAL,
                user_input_snippet TEXT,
                hil_response TEXT,
                hotline_provided BOOLEAN,
                hotline_name TEXT,
                additional_context TEXT,
                intervention_success BOOLEAN,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_crisis_user_time ON crisis_events(user_id, timestamp DESC)')
        
        # 表4：user_navigation_history（導航歷史）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_navigation_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                fracture_detected TEXT,
                fast_think_decision TEXT,
                slow_think_decision TEXT,
                final_decision TEXT,
                user_satisfaction REAL
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_nav_user ON user_navigation_history(user_id)')
        
        # 表5：intimacy_timeline（親密度時間線）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS intimacy_timeline (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                intimacy_score REAL,
                change_reason TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_intimacy_user_time ON intimacy_timeline(user_id, timestamp DESC)')
        
        conn.commit()
        logger.info("所有資料表建立完成！")
        logger.info(f"資料庫位置：{DB_PATH}")
        
    except sqlite3.Error as e:
        logger.error(f"資料庫建立失敗：{e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    create_database()
    print("fracture_map.db 已成功建立！")
    print("現在可以開始寫 fracture_map_manager.py 了。")