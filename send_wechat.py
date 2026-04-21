#!/usr/bin/env python3
"""异步发送微信消息，不阻塞主进程"""
import sys, subprocess, json, os
from datetime import datetime

ALERT_FILE = '/root/.openclaw/workspace/futures_alert_queue.json'

def send_via_gateway(msg):
    """通过OpenClaw gateway HTTP API发送"""
    import urllib.request
    token = '98b3e2eeef28335b376f123b0ee565f47fb0da23c3bdd387'
    try:
        req = urllib.request.Request(
            'http://127.0.0.1:13596/tools/invoke',
            data=json.dumps({
                "tool": "message",
                "args": {
                    "action": "send",
                    "channel": "openclaw-weixin",
                    "to": "liugang123@im.wechat",
                    "message": msg
                }
            }).encode(),
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode()
    except Exception as e:
        return str(e)

if __name__ == '__main__':
    msg = sys.argv[1] if len(sys.argv) > 1 else ''
    if not msg:
        # 读取队列发送最新告警
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE) as f:
                queue = json.load(f)
            alerts = queue.get('alerts', [])
            if alerts:
                for alert in alerts[:5]:  # 最多发5条
                    title = alert.get('title', '')
                    content = alert.get('content', '')
                    full_msg = f"{title}\n\n{content}"
                    result = send_via_gateway(full_msg)
                    print(f"Sent: {title} -> {result[:100]}")
                # 清空队列
                queue['alerts'] = []
                queue['last_sent'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(ALERT_FILE, 'w') as f:
                    json.dump(queue, f, ensure_ascii=False, indent=2)
    else:
        result = send_via_gateway(msg)
        print(result[:200])
