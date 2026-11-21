#!/bin/bash
# Serenity — macOS 启动脚本
# 双击此文件即可启动应用

cd "$(dirname "$0")"

echo "======================================"
echo "  A股Serenity"
echo "======================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    echo "请安装 Python 3.8+: brew install python"
    exit 1
fi

# 检查依赖
echo "检查依赖..."
python3 -c "import webview" 2>/dev/null || {
    echo "安装 pywebview..."
    pip3 install pywebview
}

# 启动应用
echo "启动应用..."
echo "浏览器将自动打开，或在菜单栏找到应用图标"
echo "按 Ctrl+C 退出"
echo ""

python3 mac_app.py "$@"
