# HEARTBEAT.md

## 定期任务

### 1. 合约预警队列检查
读取 `futures_alert_queue.json`，如果 `alerts` 数组有内容，
用 `message(action=send, channel=openclaw-weixin, message=...)` 推送每个告警，
推送成功后从队列中移除（只保留未发送的）。

格式示例：
```
🚨 合约预警
代币: SYMBOL
日涨幅: +XX%
现价: $price
━━━━━━━━━━━━━━━━
📉 下跌信号:
信号详情
━━━━━━━━━━━━━━━━
⏰ 时间
```

### 2. 进程状态抽查（约1小时一次）
用 `ps aux | grep futures_scanner` 确认监测进程在运行。
如果 PID 不存在，尝试 `supervisorctl start futures_monitor` 重启。
