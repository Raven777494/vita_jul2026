#!/bin/bash
# config_validate.sh - 驗證 .env 配置的完整性

echo "正在檢查 .env 配置..."

# 自動載入 .env 檔案
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
    echo "[OK] 已載入 .env 檔案"
else
    echo "[ERROR] 未找到 .env 檔案"
    exit 1
fi

# 開發環境檢查
if [ "$ENV" = "dev" ]; then
    echo "[OK] 開發環境配置"
    [ -n "$DEBUG" ] && echo "[OK] DEBUG 已設定"
    [ "$AUTH_ENABLED" = "false" ] && echo "[INFO] 開發環境建議禁用 AUTH"
    [ "$RATE_LIMIT_ENABLED" = "false" ] && echo "[INFO] 開發環境建議禁用速率限制"
fi

# 生產環境檢查
if [ "$ENV" = "prod" ]; then
    echo "生產環境配置 (強制檢查)"
    
    ERROR_COUNT=0
    
    # 檢查密鑰長度
    if [ ${#API_KEY} -lt 32 ]; then
        echo "[ERROR] API_KEY 過短 (目前 ${#API_KEY} 字元)"
        ((ERROR_COUNT++))
    else
        echo "[OK] API_KEY 長度足夠"
    fi
    
    if [ ${#JWT_SECRET} -lt 32 ]; then
        echo "[ERROR] JWT_SECRET 過短 (目前 ${#JWT_SECRET} 字元)"
        ((ERROR_COUNT++))
    else
        echo "[OK] JWT_SECRET 長度足夠"
    fi
    
    if [ ${#ENCRYPT_KEY} -lt 32 ]; then
        echo "[ERROR] ENCRYPT_KEY 過短 (目前 ${#ENCRYPT_KEY} 字元)"
        ((ERROR_COUNT++))
    else
        echo "[OK] ENCRYPT_KEY 長度足夠"
    fi
    
    # 檢查是否仍為占位符
    if [[ "$API_KEY" == *"your_long_random_key"* ]]; then
        echo "[ERROR] API_KEY 仍未真正修改"
        ((ERROR_COUNT++))
    fi
    
    if [[ "$JWT_SECRET" == *"your_long_random_jwt_secret"* ]]; then
        echo "[ERROR] JWT_SECRET 仍未真正修改"
        ((ERROR_COUNT++))
    fi
    
    # 檢查認證與安全
    if [ "$AUTH_ENABLED" = "true" ]; then
        echo "[OK] 認證已啟用"
    else
        echo "[ERROR] 生產環境必須啟用認證"
        ((ERROR_COUNT++))
    fi
    
    if [ "$RATE_LIMIT_ENABLED" = "true" ]; then
        echo "[OK] 速率限制已啟用"
    else
        echo "[ERROR] 生產環境必須啟用速率限制"
        ((ERROR_COUNT++))
    fi
    
    if [ "$DEBUG" = "false" ]; then
        echo "[OK] DEBUG 已禁用"
    else
        echo "[ERROR] 生產環境必須禁用 DEBUG"
        ((ERROR_COUNT++))
    fi
    
    # 檢查數據庫
    if [[ "$DB_HOST" == "localhost" || "$DB_HOST" == "127.0.0.1" ]]; then
        echo "[ERROR] 生產環境不應使用本地數據庫"
        ((ERROR_COUNT++))
    else
        echo "[OK] 數據庫已遠程配置: $DB_HOST"
    fi
    
    # 檢查 CORS
    if [[ "$CORS_ORIGINS" == "*" ]]; then
        echo "[ERROR] 生產環境不應使用 CORS_ORIGINS=*"
        ((ERROR_COUNT++))
    else
        echo "[OK] CORS 已限制: $CORS_ORIGINS"
    fi
    
    # 生產環境檢查結果
    echo ""
    if [ $ERROR_COUNT -eq 0 ]; then
        echo "[OK] 所有檢查已通過，可以上線"
    else
        echo "[ERROR] 檢測到 $ERROR_COUNT 個配置錯誤，禁止上線"
        exit 1
    fi
fi

echo "[OK] 配置檢查完成"