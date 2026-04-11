#!/bin/bash
# Bitget 美股现货交易机器人 启动脚本
# ======================

echo "=========================================="
echo "  Bitget 美股现货交易机器人"
echo "=========================================="

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi

# 安装依赖
echo "📦 检查依赖..."
pip3 install requests pandas numpy -q

# 运行模式选择
if [ "$1" == "live" ]; then
    echo "🚀 启动实时交易模式..."
    python3 bitget_trading_bot_main.py --mode live
elif [ "$1" == "scan" ]; then
    echo "🔍 启动单次扫描模式..."
    python3 bitget_trading_bot_main.py --mode scan
elif [ "$1" == "schedule" ]; then
    echo "⏰ 启动定时任务模式..."
    python3 bitget_trading_bot_main.py --mode schedule
else
    echo ""
    echo "用法: bash start_trading_bot.sh [mode]"
    echo ""
    echo "模式:"
    echo "  scan     - 单次扫描 (默认)"
    echo "  live     - 实时交易模式"
    echo "  schedule - 定时任务模式"
    echo ""
    echo "示例:"
    echo "  bash start_trading_bot.sh scan   # 测试扫描"
    echo "  bash start_trading_bot.sh live   # 启动实盘"
fi
