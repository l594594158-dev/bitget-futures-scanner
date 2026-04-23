# HEARTBEAT.md

## 定期任务

### 1. 合约预警队列检查
读取 `futures_alert_queue.json`，如果 `alerts` 数组有内容，
用 `message(action=send, channel=openclaw-weixin, message=...)` 推送每个告警，
推送成功后从队列中移除（只保留未发送的）。

### 2. 进程状态抽查
确认脚本在运行：
```bash
ps aux | grep -E "contract_monitor|trailing_stop_v2" | grep -v grep
```
如果任一进程不存在，重启。

### 3. 热点库扫描状态
检查 `db_hot_contracts.json` 是否正常更新（每5分钟）。

### 当前运行脚本
- `contract_monitor.py` - 合约监控（热点库扫描，入库条件：日涨幅>10%）
- `trailing_stop_v2.py` - 移动止盈（5秒监控，600秒冷却）
