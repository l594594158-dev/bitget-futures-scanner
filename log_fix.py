#!/usr/bin/env python3
"""
Bitget API 修复日志写入脚本
用法：python3 log_fix.py "问题描述" "修复内容" "文件路径" "状态"
状态：fix/known/limitation
"""

import sys
import os
from datetime import datetime

LOG_FILE = "/root/.openclaw/workspace/Bitget-API-Fix-Log.md"

TEMPLATE = """

---

## [{date} GMT+8] 第{n}次修复记录

### {title}
- **文件**：`{file}`
- **现象**：{phenomenon}
- **根因**：{root_cause}
- **修复**：
{fix_code}
- **状态**：{status}

"""

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python3 log_fix.py <问题描述> <修复内容> [文件] [状态]")
        sys.exit(1)

    title = sys.argv[1]
    fix_content = sys.argv[2]
    file_path = sys.argv[3] if len(sys.argv) > 3 else "bitget_trading_bot.py"
    status = sys.argv[4] if len(sys.argv) > 4 else "fix"

    # 读取现有记录数
    n = 1
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            content = f.read()
            n = content.count("## [20") + 1

    # 格式化修复代码
    if fix_content.startswith("```"):
        fix_code = fix_content
    else:
        fix_code = "```\n" + fix_content + "\n```"

    # 状态标签
    status_map = {
        "fix": "✅ 已修复并验证",
        "known": "⚠️ 已知限制",
        "limitation": "⚠️ 待解决",
        "revert": "❌ 已回退",
    }
    status_text = status_map.get(status, f"[{status}]")

    entry = TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n=n,
        title=title,
        file=file_path,
        phenomenon="（请补充现象描述）",
        root_cause="（请补充根因）",
        fix_code=fix_code,
        status=status_text
    )

    with open(LOG_FILE, 'a') as f:
        f.write(entry)

    print(f"✅ 已追加第{n}条修复记录到 {LOG_FILE}")
    print(f"   标题: {title}")
