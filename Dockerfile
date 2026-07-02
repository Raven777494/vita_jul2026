FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴清單
COPY requirements.txt .

# ✨ 【新增這行】先將編譯與安裝工具升級到最新版
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 安裝 Python 依賴 (原本的第 16 行)
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用代碼
COPY app app/
COPY PersonalityModule PersonalityModule/
COPY config config/
COPY dict dict/

# 建立必需目錄
RUN mkdir -p /app/logs /app/cache /app/data /app/models

# 健康檢查
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1

# 暴露端口
EXPOSE 8080

# 啟動應用
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "4"]