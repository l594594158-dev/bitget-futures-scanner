#!/bin/bash
# 美股开盘时段启动交易机器人
# 北京时间 21:30 = UTC 13:30 (夏令时)
# 
# 用法: bash start_trading.sh

echo "=========================================="
echo "  Bitget 美股交易机器人"
echo "  启动时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

cd /root/.openclaw/workspace

# 检查Python依赖
echo "检查依赖..."
python3 -c "import requests, pandas, numpy" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "安装依赖..."
    pip3 install requests pandas numpy -q
fi

# 检查API配置
echo "检查配置..."
grep -q "API_KEY = \"3d" trading_bot.py
if [ $? -ne 0 ]; then
    echo "⚠️ API配置未找到，请检查 trading_bot.py"
    exit 1
fi

echo "✅ 配置检查通过"
echo ""
echo "启动机器人..."
echo "---"

# 启动交易机器人
python3 trading_bot.py
