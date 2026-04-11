#!/bin/bash
# 交易通知推送脚本
# 将通知写入队列文件，由主进程推送

LOG_FILE="/root/.openclaw/workspace/bot_trading.log"
QUEUE_FILE="/root/.openclaw/workspace/notify_queue.txt"

tail -n 0 -F "$LOG_FILE" | while read line; do
    # 检测买卖操作
    if echo "$line" | grep -q "🟢 Buy\|🔴 Sell"; then
        # 提取消息
        msg=$(echo "$line" | sed 's/.*INFO - //')
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg" >> "$QUEUE_FILE"
    fi
done
