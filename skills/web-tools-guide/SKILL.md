---
name: web-tools-guide
description: "Web 工具策略指南。MUST trigger when 用户提到：搜索/上网/查资料/打开网站/抓取网页/获取网络信息/新闻/热点/web search/web fetch/browser use/浏览器自动化/JS 渲染页面，或需要使用 web_search/web_fetch/browser 工具时。按 search → fetch → browser 三级策略选择工具。"
---

<!-- baseDir = /root/.openclaw/workspace/skills/web-tools-guide -->

# Web 工具策略

遵循 ReAct 范式，按**从轻到重、从通用到具体**选择工具：

```
Level 1: web_search  — 关键词搜索，快速获取信息入口
Level 2: web_fetch   — 已知 URL，直接获取静态内容
Level 3: browser     — 浏览器自动化，处理复杂网页操作
```

逐级升级，每次升级告知用户原因，不要静默切换。

---

## 决策流程

```
有明确 URL？
├─ YES → 静态内容（文章/文档/API/RSS）？→ web_fetch
│        需要 JS 渲染/登录/交互/截图？  → browser
└─ NO  → web_search
         ├─ 成功 → 对结果 URL 按上述逻辑选 fetch/browser
         └─ 失败 → 引导配置（见"web_search 失败处理"）
```

---

## Level 1: web_search

**何时用**：没有明确 URL，需要搜索信息（新闻、热点、查资料、比较信息）。

**怎么用**：直接调用 `web_search`，传入搜索关键词。

**结果处理**：返回的 URL 按决策流程选 `web_fetch` 或 `browser` 深入获取。

**失败时**：见下方"web_search 失败处理"。

---

## Level 2: web_fetch

**何时用**：已知 URL，页面为静态内容——新闻文章、博客、技术文档、API 端点、RSS 源。

**怎么用**：直接调用 `web_fetch`，传入 URL。

**失败信号**：返回空白页、403、CAPTCHA、骨架 HTML → 说明需要 JS 渲染或登录态，告知用户后升级到 browser。

---

## Level 3: browser

这是最重量级的工具，也是当前问题最多的场景。以下是详细操作指引。

### 何时用

- **JS 渲染页面**：SPA、动态加载内容（微博 feed、知乎回答、小红书瀑布流）
- **需要登录态**：登录后才可见的内容、管理后台
- **页面交互**：点击按钮、填写表单、翻页、滚动加载更多
- **截图需求**：需要页面视觉信息
- **web_fetch 失败的兜底**：前一级工具无法获取有效内容

### 操作流程

**信息获取（只读）：**
1. 导航到目标 URL
2. 等待关键元素出现（不要用固定时间等待）
3. 提取所需内容（文本、链接、图片等）
4. 返回结果给用户

**登录操作：**
1. 查找登录页 URL → `read {baseDir}/references/well-known-sites.json`
2. **告知用户即将执行登录操作，获取确认**
3. 导航到登录页
4. 填写凭证（用户提供）或提示用户扫码
5. 等待登录成功，确认后继续后续操作

**页面交互：**
1. 导航到目标页面
2. 使用 CSS 选择器定位元素（辅以文本内容匹配）
3. 执行交互：点击、输入、选择、滚动
4. 等待响应/页面变化
5. 提取结果或截图

### 关键注意事项

- **登录操作必须获得用户授权** — 任何涉及账号登录的操作前，先告知用户并等待确认
- **敏感操作必须二次确认** — 发帖、删除、支付等不可逆操作
- **优先 CSS 选择器** — 比 XPath 更稳定，辅以文本匹配
- **智能等待** — 等待目标元素出现，而非 `sleep(3)` 式固定等待
- **CAPTCHA/验证码** — 无法自动处理时告知用户需手动介入
- **页面加载超时** — 设置合理超时，失败时告知用户并建议重试
- **多步操作保持状态** — 登录后的后续操作复用同一浏览器上下文，不要重新打开

---

## web_search 失败处理

**当 `web_search` 返回错误时，不要静默降级，必须引导配置：**

1. **`read {baseDir}/references/web-search-config.md`**
2. 按文件中 Step 1 **原样输出**配置引导给用户（不要改写表格或省略内容）
3. 等待用户回复：
   - 用户提供 API Key → 再次 `read {baseDir}/references/web-search-config.md`，按 Step 2-5 执行
   - 用户说"暂不配置" → 进入降级方案
   - 其他回复 → 正常响应
4. **降级方案**（仅在用户明确拒绝配置后）：
   - `read {baseDir}/references/well-known-sites.json` 获取常用网站 URL
   - 用 `web_fetch` 直接获取目标网站内容
   - 仍不行 → 升级到 `browser`

---

## 常用网站

需要常用网站 URL 时（登录页、搜索引擎、热搜榜等）：

```
read {baseDir}/references/well-known-sites.json
```

通过 key 查找（如 `social.weibo.login`、`search.baidu`）。带 `{query}` 的 URL 替换为实际搜索词。
