#!/bin/bash
# 定时启动脚本 - 每天美股开盘前运行
# 北京时间 21:25 启动 (美股21:30开盘)

WORKDIR="/root/.openclaw/workspace"
LOGFILE="$WORKDIR/bot_trading.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') - 准备启动交易机器人" >> $LOGFILE

cd $WORKDIR

# 启动机器人 (后台运行)
nohup python3 trading_bot.py >> $LOGFILE 2>&1 &

echo "$(date '+%Y-%m-%d %H:%M:%S') - 交易机器人已启动, PID: $!" >> $LOGFILE
