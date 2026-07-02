
# run_judgment.py
# 深夜審判室 - 執行腳本
# 用法: python run_judgment.py [--debug] [--user_id USER_ID] [--batch_size BATCH_SIZE]
# 建議設定 Crontab: 06 23 * * * python /path/to/app/run_judgment.py

import asyncio
import logging
import sys
import os
import argparse
import traceback
import requests
import json
from datetime import datetime

# 確保專案路徑在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.nightly_logic import NightlyJudgment
from app.config import config

# 配置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOGS_DIR / "judgment_room.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("vita.run_judgment")

def send_alert(error_msg: str, details: str = ""):
    """Send alert to notification channels (Slack) if critical failure occurs."""
    if not config.ENABLE_SLACK or not config.SLACK_WEBHOOK_URL:
        logger.warning("Slack alerting disabled or URL not set. Skipping alert.")
        return

    payload = {
        "text": (
            f"**CRITICAL: Nightly Judgment Failed**\n"
            f"**Environment:** {config.ENV}\n"
            f"**Time:** {datetime.now().isoformat()}\n"
            f"**Error:** {error_msg}\n"
            f"```{details}```"
        )
    }
    
    try:
        response = requests.post(config.SLACK_WEBHOOK_URL, json=payload, timeout=5)
        if response.status_code != 200:
            logger.error(f"Failed to send Slack alert: {response.text}")
        else:
            logger.info("Critical alert sent to Slack.")
    except Exception as e:
        logger.error(f"Error sending Slack alert: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Vita Nightly Judgment Room")
    parser.add_argument('--debug', action='store_true', help="Run in debug mode (no DB commit or simplified flow)")
    parser.add_argument('--user_id', type=str, help="Target specific user ID for judgment")
    parser.add_argument('--batch_size', type=int, default=50, help="Batch size for concurrent processing (default: 50)")
    args = parser.parse_args()

    print(">>> 正在啟動深夜審判室...")
    if args.debug:
        print(">>> DEBUG MODE ENABLED")
    if args.user_id:
        print(f">>> Targeting Single User: {args.user_id}")
    if args.batch_size:
        print(f">>> Batch Size: {args.batch_size}")

    try:
        judge = NightlyJudgment(batch_size=args.batch_size)
        await judge.run(target_user_id=args.user_id, debug_mode=args.debug)
        print(">>> 審判完成。")
        
    except Exception as e:
        error_msg = str(e)
        trace_str = traceback.format_exc()
        print(f">>> 發生致命錯誤: {error_msg}")
        logger.critical(f"Fatal error in main execution: {error_msg}\n{trace_str}")
        
        # Send Alert
        send_alert(error_msg, trace_str)
        sys.exit(1)

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
