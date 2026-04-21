#!/bin/bash
# 移动止盈v2启动脚本

WORKSPACE='/root/.openclaw/workspace'
PID_FILE="$WORKSPACE/trailing_stop_v2.pid"

case "$1" in
    start)
        cd "$WORKSPACE"
        python3 trailing_stop_v2.py start
        ;;
    stop)
        cd "$WORKSPACE"
        python3 trailing_stop_v2.py stop
        ;;
    restart)
        cd "$WORKSPACE"
        python3 trailing_stop_v2.py restart
        ;;
    status)
        cd "$WORKSPACE"
        python3 trailing_stop_v2.py status
        ;;
    log)
        cd "$WORKSPACE"
        python3 trailing_stop_v2.py log
        ;;
    db)
        cd "$WORKSPACE"
        python3 trailing_stop_v2.py db
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|log|db}"
        exit 1
        ;;
esac
