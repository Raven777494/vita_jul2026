#!/bin/bash
# config_validator.sh - Vita 3.0 智慧路徑驗證腳本

echo "Vita 3.0 配置驗證檢查清單 (v5.5.5 相容版)"
echo "================================================="

# 1. 智慧尋找 .env 檔案位置
ENV_PATH=".env"

if [ ! -f "$ENV_PATH" ] && [ -f "../.env" ]; then
    ENV_PATH="../.env"
    echo "💡 提示: 在當前目錄未找到 .env，已自動切換至上層目錄載入。"
fi

# 2. 讀取並強力清洗 .env 檔案 (相容 Windows/Linux 換行符號)
if [ -f "$ENV_PATH" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        # 清理 Windows 换行符
        clean_line=$(echo "$line" | tr -d '\r')
        
        # 跳过注释和空行
        [[ "$clean_line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "$clean_line" ]] && continue
        
        # 安全导出（使用 set -a/+a 而不是 eval）
        if [[ "$clean_line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            export "$clean_line"
        fi
    done < "$ENV_PATH"
else
    echo "❌ ERROR: 找不到 .env 檔案！"
    echo "   請確認 .env 存在於當前目錄或上層目錄中。"
    exit 1
fi

# 輔助函式：將浮點數（例如 3.0）轉成整數（3）以便 Bash 進行安全比較
to_int() {
    echo "${1%.*}"
}

# =========================================================
# [1] 環境與核心伺服器檢查
# =========================================================
echo "[1] 環境與核心伺服器檢查"
[ -n "$ENV" ] && echo "  ✅ OK: ENV=$ENV" || echo "  ❌ ERROR: ENV 未設置"
[ -n "$HOST" ] && echo "  ✅ OK: HOST=$HOST" || echo "  ❌ ERROR: HOST 未設置"
[ -n "$PORT" ] && echo "  ✅ OK: PORT=$PORT" || echo "  ❌ ERROR: PORT 未設置"

# =========================================================
# [2] 資料庫配置檢查
# =========================================================
echo -e "\n[2] 資料庫配置檢查"
[ -n "$DATABASE_URL" ] && echo "  ✅ OK: DATABASE_URL 格式已導出" || echo "  ❌ ERROR: DATABASE_URL 未設置"

if [ -n "$DB_POOL_SIZE" ]; then
    INT_POOL=$(to_int "$DB_POOL_SIZE")
    if [ "$INT_POOL" -ge 10 ] 2>/dev/null; then
        echo "  ✅ OK: DB_POOL_SIZE=$DB_POOL_SIZE (符合高併發優化規格)"
    else
        echo "  ⚠️ WARNING: DB_POOL_SIZE=$DB_POOL_SIZE 生產環境建議 >= 10"
    fi
else
    echo "  ❌ ERROR: DB_POOL_SIZE 未設置"
fi

# =========================================================
# [3] Redis 配置檢查
# =========================================================
echo -e "\n[3] Redis 配置檢查"
[ -n "$REDIS_HOST" ] && echo "  ✅ OK: REDIS_HOST=$REDIS_HOST" || echo "  ❌ ERROR: REDIS_HOST 未設置"

if [ -n "$REDIS_CONNECT_TIMEOUT" ]; then
    INT_R_TIMEOUT=$(to_int "$REDIS_CONNECT_TIMEOUT")
    if [ "$INT_R_TIMEOUT" -le 10 ] 2>/dev/null; then
        echo "  ✅ OK: REDIS_CONNECT_TIMEOUT=$REDIS_CONNECT_TIMEOUT (連線快取控制良好)"
    else
        echo "  ⚠️ WARNING: REDIS_CONNECT_TIMEOUT=$REDIS_CONNECT_TIMEOUT 設置過長"
    fi
else
    echo "  ❌ ERROR: REDIS_CONNECT_TIMEOUT 未設置"
fi

# =========================================================
# [4] LLM 服務端點檢查 (Soul/Vocal/Logic/Embedding/Emotion)
# =========================================================
echo -e "\n[4] LLM 服務端點檢查"
for service in SOUL VOCAL LOGIC EMBEDDING EMOTION; do
  url_var="${service}_URL"
  timeout_var="${service}_TIMEOUT"
  model_var="${service}_MODEL"
  
  url=${!url_var}
  timeout=${!timeout_var}
  model=${!model_var}
  
  if [ -n "$url" ]; then
      echo "  ✅ OK: ${service}_URL=$url [模型: $model]"
  else
      echo "  ❌ ERROR: ${service}_URL 未設置！系統核心將斷聯"
  fi
  
  if [ -n "$timeout" ]; then
      echo "  │   └── 逾時控管: ${service}_TIMEOUT=${timeout}s"
  else
      echo "  │   └── ⚠️ WARNING: ${service}_TIMEOUT 未設置，可能會造成線程阻塞"
  fi
done

# =========================================================
# [5] Orchestrator 核心超時配置檢查 (PerformanceConfig 同步)
# =========================================================
echo -e "\n[5] Orchestrator 核心超時配置檢查"
for timeout in EMOTION_ANALYSIS_TIMEOUT EMBEDDING_GENERATION_TIMEOUT NAVIGATOR_TIMEOUT PERSONALITY_ANCHOR_TIMEOUT; do
  val=${!timeout}
  if [ -n "$val" ]; then
      echo "  ✅ OK: $timeout=$val"
  else
      echo "  ❌ ERROR: 核心超時模組 $timeout 未設置，無法同步 orchestrator.py"
  fi
done

# =========================================================
# [6] 敏感資訊與安全性檢查
# =========================================================
echo -e "\n[6] 敏感資訊安全深度檢查"
for secret in API_KEY JWT_SECRET ENCRYPT_KEY SECRET_KEY; do
  val=${!secret}
  len=${#val}
  
  if [[ "$val" == *"change_me"* ]]; then
      echo "  🚨 CRITICAL: $secret 內含 'change_me' 預設密鑰字樣！安全防禦失效！"
  elif [ -n "$val" ] && [ "$len" -ge 32 ]; then
      echo "  ✅ OK: $secret 長度充足 ($len 字元，已脫敏隱藏)"
  else
      echo "  ⚠️ WARNING: $secret 安全長度不足 32 位元 ($len 字元)，極易遭受暴力破解"
  fi
done

echo -e "\n================================================="
echo " 🎉 驗證完成！請根據上述報告調整您的部署策略。"