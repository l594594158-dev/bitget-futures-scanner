#!/bin/bash
# 周一美股自动买入脚本
cd /root/.openclaw/workspace
python3 auto_buy_monday.py >> /root/.openclaw/workspace/cron_log.txt 2>&1
