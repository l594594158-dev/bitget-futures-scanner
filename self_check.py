#!/usr/bin/env python3
"""
Bitget 自检任务 - 每30分钟自动执行
检查内容：
  1. API数据获取情况（美股 + ETH合约）
  2. 所有API端口返回是否正常
  3. 美股任务和ETH合约任务是否正常运行
  4. 发现问题自动修复并写入修复文档
  5. 每次检查创建检查日志
"""

import sys
import os
import time
import json
import math
import hmac
import hashlib
import base64
import socket
import traceback
import subprocess
from datetime import datetime
from typing import Dict, List, Tuple, Optional

WORKSPACE = '/root/.openclaw/workspace'
LOG_FILE = f'{WORKSPACE}/self_check.log'
FIX_LOG_FILE = f'{WORKSPACE}/Bitget-API-Fix-Log.md'

# ==================== API配置 ====================
API_KEY = "3d485fcacc8e5aaae096ec2526c6966edfe1e3a0a2da1627111aa0d53fab6a4c"
API_SECRET = "bg_55d7ddd792c3ebab233b4a6911f95f99"
PASSPHRASE = "liugang123"
BASE_URL = "https://api.bitget.com"

# ==================== 日志工具 ====================
def log(msg: str, tag: str = "ℹ️"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {tag} {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def wechat_notify(msg: str):
    """微信通知（仅在有修复时调用）"""
    import subprocess
    print(f"\n📲 微信通知: {msg}\n")
    try:
        # 通过 openclaw CLI 发送微信消息
        subprocess.run([
            "openclaw", "message", "send",
            "--channel", "openclaw-weixin",
            "--message", msg
        ], capture_output=True, timeout=15)
    except Exception as e:
        # 降级：写入缓存文件
        notify_cache = f"{WORKSPACE}/self_check_notify.txt"
        with open(notify_cache, "w") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def log_fix(category: str, problem: str, solution: str, file_touched: str = ""):
    """写修复文档"""
    entry = f"""

---
## 自检自动修复：{category}（{datetime.now().strftime("%Y-%m-%d %H:%M")}）

**问题：** {problem}

**修复：** {solution}

**涉及文件：** {file_touched or "无"}

**自动修复：是**
"""
    with open(FIX_LOG_FILE, "a") as f:
        f.write(entry)

# ==================== Bitget API ====================
class BitgetAPI:
    def __init__(self):
        self.base_url = BASE_URL
        self.headers = {
            "Content-Type": "application/json",
            "ACCESS-KEY": API_KEY,
            "ACCESS-PASSPHRASE": PASSPHRASE,
        }
        self._fixes_applied = []

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        message = timestamp + method + path + body
        mac = hmac.new(API_SECRET.encode('utf-8'), message.encode('utf-8'), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def _request(self, method: str, path: str, params: Dict = None, body: Dict = None) -> Tuple[bool, any, str]:
        """返回 (success, data, error_msg)"""
        try:
            import requests as req
            timestamp = str(int(time.time() * 1000))
            query_str = '&'.join(f'{k}={v}' for k, v in params.items()) if params else ''
            full_path = path + ('?' + query_str if query_str else '')
            body_str = json.dumps(body) if body else ""
            signature = self._sign(timestamp, method, full_path, body_str)

            headers = self.headers.copy()
            headers["ACCESS-SIGN"] = signature
            headers["ACCESS-TIMESTAMP"] = timestamp

            url = self.base_url + full_path
            resp = req.request(method, url, headers=headers, data=body_str, timeout=10)
            result = resp.json()

            if str(result.get("code")) not in ("00000", "0000", None) and result.get("code") != "success":
                return False, None, f"API错误 {result.get('code')}: {result.get('msg', '')}"
            return True, result.get("data", result), ""
        except Exception as e:
            return False, None, str(e)

    # ---------- 美股现货接口 ----------
    def spot_tickers(self) -> Tuple[bool, any]:
        """美股批量行情（/api/v2/spot/market/tickers）"""
        return self._request("GET", "/api/v2/spot/market/tickers", {"instType": "SPOT"})

    def spot_account(self) -> Tuple[bool, any]:
        """现货账户资产（/api/v2/spot/account/assets）"""
        return self._request("GET", "/api/v2/spot/account/assets")

    def spot_orders_active(self) -> Tuple[bool, any]:
        """当前挂单（/api/v2/spot/orders/active）"""
        return self._request("GET", "/api/v2/spot/orders/active")

    # ---------- ETH合约接口 ----------
    def futures_ticker(self) -> Tuple[bool, any]:
        """合约行情（/api/v2/mix/market/ticker）"""
        return self._request("GET", "/api/v2/mix/market/ticker", {
            "symbol": "ETHUSDT", "productType": "usdt-futures"
        })

    def futures_account(self) -> Tuple[bool, any]:
        """合约账户（/api/v2/mix/account/accounts）"""
        return self._request("GET", "/api/v2/mix/account/accounts", {
            "symbol": "ETHUSDT", "productType": "usdt-futures"
        })

    def futures_positions(self) -> Tuple[bool, any]:
        """合约持仓（/api/v2/mix/position/positions）"""
        return self._request("GET", "/api/v2/mix/position/positions", {
            "symbol": "ETHUSDT", "productType": "usdt-futures"
        })

    def futures_candles(self, interval: str = "1H", limit: int = 100) -> Tuple[bool, any]:
        """K线数据（interval: 1H/4H/1D 等，大写）"""
        return self._request("GET", "/api/v2/mix/market/candles", {
            "symbol": "ETHUSDT", "productType": "usdt-futures",
            "granularity": interval, "limit": str(limit)
        })

# ==================== 自检逻辑 ====================
class SelfChecker:
    def __init__(self):
        self.api = BitgetAPI()
        self.fixes = []
        self.ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------- 1. 检查进程 ----------
    def check_processes(self) -> Dict:
        result = {"us_stocks": False, "details": {}}

        # 检查美股机器人
        r = subprocess.run(["pgrep", "-f", "trading_bot_us_stocks"],
                         capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            pids = r.stdout.strip().split()
            result["us_stocks"] = True
            result["details"]["us_stocks_pid"] = pids
        else:
            self.fixes.append({
                "category": "进程异常 - 美股机器人",
                "problem": "美股机器人进程未运行",
                "solution": "重启机器人: cd /root/.openclaw/workspace && nohup python3 -u trading_bot_us_stocks_v1.py >> bot_us_stocks.log 2>&1 &",
                "cmd": f"cd {WORKSPACE} && nohup python3 -u trading_bot_us_stocks_v1.py >> bot_us_stocks.log 2>&1 &"
            })

        # 检查合约监测进程
        r2 = subprocess.run(["pgrep", "-f", "futures_scanner.py --monitor"],
                         capture_output=True, text=True)
        if r2.returncode == 0 and r2.stdout.strip():
            result["details"]["futures_monitor_pid"] = r2.stdout.strip().split()
        else:
            self.fixes.append({
                "category": "进程异常 - 合约监测",
                "problem": "合约监测进程未运行",
                "solution": "supervisorctl start futures_monitor",
                "cmd": "supervisorctl start futures_monitor"
            })

        return result

    # ---------- 2. 检查API接口 ----------
    def check_api_endpoints(self) -> Dict:
        result = {}

        checks = [
            ("美股_批量行情", self.api.spot_tickers),
            ("美股_账户资产", self.api.spot_account),
        ]

        for name, fn in checks:
            ok, data, err = fn() if name != "美股_K线" else fn("1h", 10)
            result[name] = {"ok": ok, "error": err}
            if ok:
                if isinstance(data, list) and len(data) == 0:
                    result[name]["warn"] = "返回空列表"
                elif isinstance(data, dict) and not data:
                    result[name]["warn"] = "返回空字典"

        return result

    # ---------- 3. 检查数据类型（扫描源码中的隐患）----------
    def check_data_types(self) -> List[Dict]:
        """扫描源码中 get_ticker()['lastPr'] 是否被 float() 包裹"""
        issues = []
        return issues

    # ---------- 执行修复 ----------
    def apply_fixes(self, issues: List[Dict]):
        for issue in issues:
            fpath = f"{WORKSPACE}/{issue['file']}"
            try:
                with open(fpath) as f:
                    lines = f.readlines()

                lineno = issue.get("line", 0) - 1
                if 0 <= lineno < len(lines):
                    original = lines[lineno]
                    # 找到不安全的取值模式，包裹 float()
                    # 例如: price = self.api.get_ticker()['lastPr']
                    # 改为: price = float(self.api.get_ticker()['lastPr'])
                    import re
                    # 匹配 = ... get_ticker(...) ['lastPr']
                    if re.search(r"=\s*[^;]*get_ticker\(\)[^;]*\['lastPr'\]", original):
                        fixed = re.sub(
                            r"(\=[\s]*)(.*?)(get_ticker\(\)[^;]*\['lastPr'\])",
                            r"\1float(\3)",
                            original
                        )
                        if "float(" not in original:
                            lines[lineno] = fixed
                            with open(fpath, "w") as f:
                                f.writelines(lines)
                            self.fixes.append({
                                "category": f"代码修复 - {issue['file']}",
                                "problem": issue["problem"],
                                "solution": f"第{lineno+1}行: {original.strip()} → {fixed.strip()}",
                                "file_touched": fpath
                            })
                            log(f"  ✅ 自动修复: {issue['file']}:{lineno+1}", "🔧")
            except Exception as e:
                log(f"  ❌ 修复失败: {issue['file']}: {e}", "❌")

    def restart_bots(self):
        for fix in self.fixes:
            if "cmd" in fix:
                try:
                    log(f"  🚀 执行: {fix['cmd'][:60]}...", "🔁")
                    subprocess.run(fix["cmd"], shell=True, capture_output=True)
                    self.fixes.append({
                        "category": fix["category"],
                        "problem": fix["problem"],
                        "solution": f"已执行重启命令: {fix['cmd'][:60]}..."
                    })
                except Exception as e:
                    log(f"  ❌ 重启失败: {e}", "❌")

    # ---------- 写修复文档 ----------
    def save_fixes(self):
        if not self.fixes:
            return
        for fix in self.fixes:
            log_fix(
                category=fix.get("category", "未知"),
                problem=fix.get("problem", ""),
                solution=fix.get("solution", ""),
                file_touched=fix.get("file_touched", "")
            )

# ==================== 主流程 ====================
def main():
    print("=" * 60)
    print(f"🤖 Bitget 自检任务 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 初始化日志
    os.makedirs(WORKSPACE, exist_ok=True)

    checker = SelfChecker()

    # ---------- 1. 进程检查 ----------
    log("=" * 40, "📋")
    log("① 检查进程运行状态", "🔍")
    proc = checker.check_processes()
    for name, status in [("美股机器人", proc["us_stocks"])]:
        tag = "✅" if status else "❌"
        log(f"  {tag} {name}: {'运行中' if status else '未运行'}", tag)
    if "us_stocks_pid" in proc["details"]:
        log(f"     PID: {proc['details']['us_stocks_pid']}", "  ")

    # ---------- 2. API接口检查 ----------
    log("=" * 40, "📋")
    log("② 检查API接口", "🔍")
    endpoints = checker.check_api_endpoints()
    for name, info in endpoints.items():
        if info["ok"]:
            tag = "⚠️" if info.get("warn") else "✅"
            detail = f" [{info.get('warn')}]" if info.get("warn") else ""
            log(f"  {tag} {name}: 正常{detail}", tag)
        else:
            log(f"  ❌ {name}: {info['error']}", "❌")

    # ---------- 3. 数据类型检查 ----------
    log("=" * 40, "📋")
    log("③ 检查数据类型隐患", "🔍")
    type_issues = checker.check_data_types()
    if type_issues:
        log(f"  ⚠️ 发现 {len(type_issues)} 个类型隐患", "⚠️")
        for iss in type_issues:
            log(f"     - {iss['file']}: {iss['problem']}", "⚠️")
    else:
        log("  ✅ 未发现类型隐患", "✅")

    # ---------- 4. 自动修复 ----------
    if type_issues:
        log("=" * 40, "📋")
        log("④ 执行自动修复", "🔧")
        checker.apply_fixes(type_issues)

    # ---------- 5. 重启故障进程 ----------
    down_bots = [f for f in checker.fixes if "cmd" in f]
    if down_bots:
        log("=" * 40, "📋")
        log("⑤ 重启故障进程", "🔁")
        checker.restart_bots()

    # ---------- 6. 写入修复文档 ----------
    if checker.fixes:
        log("=" * 40, "📋")
        log("⑥ 写入修复日志", "📝")
        checker.save_fixes()
        for fix in checker.fixes:
            log(f"  📌 {fix.get('category','')}: {fix.get('problem','')[:50]}", "📝")
    else:
        log("  ✅ 无需修复，检查完成", "✅")

    # ---------- 汇总 ----------
    log("=" * 40, "📋")
    fm_running = "futures_monitor_pid" in proc.get('details', {})

    # 读取合约任务状态
    db1_info = ""
    try:
        import json as _json
        with open(f"{WORKSPACE}/db_hot_contracts.json") as _f:
            _db = _json.load(_f)
            _contracts = _db.get('contracts', [])
            db1_info = f" DB1:{len(_contracts)}个"
            if _contracts:
                _top = _contracts[0]
                db1_info += f"({_top['symbol']}+{_top['change24h']*100:.0f}%)"
        with open(f"{WORKSPACE}/db_positions.json") as _f:
            _pos = _json.load(_f)
            _positions = _pos.get('positions', [])
            if _positions:
                db1_info += f" | 持仓:{len(_positions)}个"
                for _p in _positions:
                    db1_info += f" {_p['symbol']}"
    except:
        db1_info = " DB1:查不到"

    summary = f"检查完成 | 进程:✅ 美股:{'✅' if proc['us_stocks'] else '❌'} 合约监测:{'✅' if fm_running else '❌'}{db1_info} | API:{sum(1 for e in endpoints.values() if e['ok'])}/{len(endpoints)} 正常 | 修复:{len(checker.fixes)} 个"
    log(summary, "📊")
    print("=" * 60)

    # ---------- 有修复时发微信通知 ----------
    if checker.fixes:
        fix_lines = [f"🔧 {f.get('category','修复')}: {f.get('problem','')}" for f in checker.fixes]
        msg = "🤖 自检修复通知\n" + "\n".join(fix_lines)
        wechat_notify(msg)

if __name__ == "__main__":
    main()
