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
如果 PID 不存在，尝试重启。

### 3. API端口数据检查 + 自动修复（每次心跳）
每次心跳检查API数据获取是否正常，发现失败自动修复：

**检查步骤：**
1. 调用 `futures_scanner.get_position_size('SCRTUSDT')` 验证持仓API
2. 调用 `futures_scanner.get_ticker('SCRTUSDT')` 验证行情API
3. 检查返回数据是否有效（非None、非空）

**自动修复流程：**
```
API失败1次 → 等待5秒重试
API失败2次 → 等待5秒重试
API失败3次 → 重启主机器人 (kill + nohup restart)
API失败5次 → 重启移动止盈脚本 (trailing_stop_v2.sh restart)
```

**检查命令：**
```bash
cd /root/.openclaw/workspace && python3 -c "
import sys; sys.path.insert(0, '.')
import futures_scanner as fs
pos = fs.get_position_size('SCRTUSDT')
ticker = fs.get_ticker('SCRTUSDT')
print(f'持仓API: {pos} | 行情API: {ticker.get(\"lastPr\") if ticker else None}')
"
```
