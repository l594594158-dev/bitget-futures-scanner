#!/bin/bash
WORKSPACE='/root/.openclaw/workspace'
PYTHON='python3'
SCRIPT="$WORKSPACE/trailing_stop.py"
PID_FILE="$WORKSPACE/trailing_stop.pid"
LOG_FILE="$WORKSPACE/trailing_stop.log"

case "$1" in
  start)
    echo "启动移动止盈监控..."
    cd $WORKSPACE
    nohup $PYTHON $SCRIPT --daemon > $LOG_FILE 2>&1 &
    echo $! > $PID_FILE
    sleep 2
    if ps -p $(cat $PID_FILE) > /dev/null 2>&1; then
      echo "✅ 已启动 (PID: $(cat $PID_FILE))"
    else
      echo "❌ 启动失败"
    fi
    ;;
  stop)
    if [ -f $PID_FILE ]; then
      PID=$(cat $PID_FILE)
      kill $PID 2>/dev/null
      rm -f $PID_FILE
      echo "✅ 已停止"
    else
      echo "未运行"
    fi
    ;;
  status)
    if [ -f $PID_FILE ]; then
      PID=$(cat $PID_FILE)
      if ps -p $PID > /dev/null 2>&1; then
        echo "✅ 运行中 (PID: $PID)"
      else
        echo "❌ PID存在但进程已停止"
        rm -f $PID_FILE
      fi
    else
      echo "❌ 未运行"
    fi
    ;;
  restart)
    $0 stop
    sleep 1
    $0 start
    ;;
  log)
    tail -20 $LOG_FILE
    ;;
  *)
    echo "用法: $0 {start|stop|status|restart|log}"
    ;;
esac
