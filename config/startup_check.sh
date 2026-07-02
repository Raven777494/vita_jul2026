#!/bin/bash
# startup_check.sh - 系統啟動前驗證
#D:\Desktop\engine7b\config>bash startup_check.sh

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"

echo "============================================"
echo "VITA 2.0 - Configuration Startup Check"
echo "============================================"
echo ""

# 檢查 Python 環境
echo "Checking Python environment..."
python_version=$(python --version 2>&1)
echo "  Python: $python_version"

# 檢查必要的目錄
echo ""
echo "Checking required directories..."
required_dirs=(
    "models"
    "config"
    "logs"
    "data"
    "cache"
)

for dir in "${required_dirs[@]}"; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        echo "  ✓ $dir/"
    else
        echo "  ✗ $dir/ (missing)"
        mkdir -p "$PROJECT_ROOT/$dir"
        echo "    Created $dir/"
    fi
done

# 檢查配置文件
echo ""
echo "Checking configuration files..."
config_files=(
    "config/llm_services.yml"
    "docker-compose.yml"
)

for file in "${config_files[@]}"; do
    if [ -f "$PROJECT_ROOT/$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ $file (missing)"
    fi
done

# 運行 Python 配置驗證
echo ""
echo "Running Python configuration validation..."
cd "$PROJECT_ROOT"

python -c "
import sys
sys.path.insert(0, '.')
from app.config_validation import ConfigValidator
valid, results = ConfigValidator.validate_all()
ConfigValidator.print_report(results)
sys.exit(0 if valid else 1)
" || {
    echo ""
    echo "Configuration validation failed!"
    exit 1
}

echo ""
echo "============================================"
echo "Startup check completed successfully!"
echo "============================================"
exit 0