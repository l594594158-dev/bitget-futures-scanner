#!/bin/bash
cd /root/.openclaw/workspace
nohup python3 surge_trader.py start > surge_trader.out.log 2>&1 &
echo "PID: $!"
