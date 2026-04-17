# AI Agent 快速配置指南

本文档供 AI Agent 参考，快速完成项目从零到运行的全部配置。

---

## 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/Sy2RK/AI-Tools-Competitor-Monitor.git
cd AI-Tools-Competitor-Monitor

# 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 安装 ffmpeg（视频压缩依赖）
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
# 也可依赖 imageio-ffmpeg 自动获取，无需系统安装
```

---

## 2. 配置 `.env` 文件

在项目根目录创建 `.env` 文件，包含以下变量：

```env
# ===== 必填 =====
# RapidAPI 密钥（TikTok/Instagram/Twitter 爬虫），支持多 Key 逗号分隔轮换
RAPIDAPI_KEY=your_rapidapi_key_here

# OpenRouter API 密钥（周报 AI 分析）
OPENROUTER_API_KEY=your_openrouter_key_here

# ===== 推荐 =====
# Google YouTube Data API v3 密钥（配置后优先使用官方 API，精确时间戳 + Shorts 支持）
YOUTUBE_API_KEY=your_youtube_api_key_here

# ===== 可选 =====
# 阿里云 DashScope 密钥（视频 AI 分析，不填则跳过视频分析）
DASHSCOPE_API_KEY=your_dashscope_key_here

# 飞书群机器人 Webhook（不填则不推送飞书）
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-hook-id

# 企业微信群机器人 Webhook（不填则不推送企微）
WEWORK_WEBHOOK_URL=

# Jina Reader 密钥（官网爬虫增强，不填则仅用 RSS + Requests）
JINA_API_KEY=

# 视频下载代理（访问 YouTube/googlevideo 用，海外服务器留空）
VIDEO_DOWNLOAD_PROXY=

# 视频AI分析每次最多分析多少条视频（默认5）
VIDEO_ANALYSIS_MAX_POSTS=5
```

### 密钥获取方式

| 密钥 | 获取地址 | 说明 |
|------|----------|------|
| `RAPIDAPI_KEY` | https://rapidapi.com/ | 注册后 在 Apps → Application → Key 获取；需订阅以下 API：`tiktok-scraper-api2`、`instagram-scraper-api2`、`twitter241`、`youtube138` |
| `OPENROUTER_API_KEY` | https://openrouter.ai/ | 注册后在 Keys 页面创建 |
| `YOUTUBE_API_KEY` | https://console.cloud.google.com/ | 启用 YouTube Data API v3 → 创建 API Key |
| `DASHSCOPE_API_KEY` | https://dashscope.console.aliyun.com/ | 阿里云控制台开通 DashScope 服务后获取 |
| `FEISHU_WEBHOOK_URL` | 飞书群设置 → 机器人 → 添加自定义机器人 | 复制 Webhook 地址 |

---

## 3. 配置竞品名单 `config/config.yaml`

编辑 `config/config.yaml`，在 `competitors` 列表中添加/修改要监控的产品：

```yaml
competitors:
- name: 产品名称
  priority: high        # high / medium / low
  platforms:
  - username: 账号用户名
    type: tiktok        # tiktok / instagram / twitter / youtube / website
    enabled: true
    url: https://www.tiktok.com/@username
  # 每个平台一条配置，不需要的平台不写即可
```

### 各平台配置字段说明

| 平台 | 必填字段 | 可选字段 | 示例 |
|------|---------|---------|------|
| `tiktok` | `username`, `url` | `sec_uid` | `username: pixverse`, `url: https://www.tiktok.com/@pixverse` |
| `instagram` | `username`, `url` | — | `username: pixverse_official`, `url: https://www.instagram.com/pixverse_official/` |
| `twitter` | `username`, `url` | `user_id` | `username: pixverse_`, `url: https://x.com/pixverse_` |
| `youtube` | `username`, `url` | `channel_id` | `username: PixVerse_Official`, `url: https://www.youtube.com/@PixVerse_Official` |
| `website` | `url` | — | `url: https://pixverse.ai` |

> **注意**：`channel_id` 和 `user_id` 留空时系统会自动通过 API 查询获取。`sec_uid` 用于 TikTok，留空时自动获取。

---

## 4. 验证配置

### 4.1 测试每日爬虫

```bash
source .venv/bin/activate
export PYTHONPATH="$(pwd):$PYTHONPATH"

# 抓取前一天数据（验证所有平台是否能正常获取）
python scrapers/daily_scraper.py --days-ago 1
```

预期输出：每个产品逐平台打印抓取结果，如 `✅ TikTok @pixverse: 3 条帖子`。

### 4.2 测试周报生成

```bash
# 生成过去7天的周报（替换日期为实际值）
python workflows/period_workflow.py --start-date 2026-04-10 --end-date 2026-04-16
```

预期输出：提取数据 → AI 分析 → 生成飞书卡片 → 推送。

### 4.3 仅测试不推送

```bash
python workflows/period_workflow.py --start-date 2026-04-10 --end-date 2026-04-16 --skip-send
```

---

## 5. 安装定时任务

```bash
# 一键安装所有定时任务
./setup-cron.sh
```

安装后定时任务：

| 任务 | 时间 | 说明 |
|------|------|------|
| 每日爬虫 | 每天 10:00 | 爬取前一天各平台数据 |
| 每周周报 | 每周一 10:30 | 生成过去7天竞品周报并推送 |
| 数据库备份 | 每天 02:00 | SQLite 备份，保留最近 10 份 |
| 日志清理 | 每周日 03:00 | 清理 30 天前日志、7 天前视频缓存 |

---

## 6. 常见问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| TikTok/Instagram/Twitter 返回空数据 | RapidAPI Key 额度用完或未订阅对应 API | 检查 Key 有效性，更换或添加多个 Key |
| YouTube 数据缺少 Shorts | 未配置 `YOUTUBE_API_KEY`，降级到 RapidAPI 不支持 Shorts | 配置 `YOUTUBE_API_KEY` |
| 视频分析跳过 | 未配置 `DASHSCOPE_API_KEY` | 配置 DashScope 密钥 |
| YouTube 视频下载失败 | 服务器无法访问 googlevideo.com | 配置 `VIDEO_DOWNLOAD_PROXY` |
| 飞书推送失败 | Webhook 地址无效或过期 | 重新获取飞书群机器人 Webhook |
| 周报无数据 | 数据库中该时间段无爬取记录 | 先运行每日爬虫积累数据 |
| 数据库中有旧产品数据 | 旧项目残留 | 运行 `python -c "from database.competitor_db import CompetitorDatabaseDB; db=CompetitorDatabaseDB(); ..."` 清理 |

---

## 7. 项目核心文件速查

| 文件 | 用途 |
|------|------|
| `config/config.yaml` | 竞品名单 + 平台账号（唯一数据源） |
| `.env` | API 密钥 + 推送地址 |
| `db/competitor_data.db` | SQLite 数据库（爬取数据 + 周报缓存） |
| `scrapers/daily_scraper.py` | 每日爬虫入口 |
| `workflows/period_workflow.py` | 周报完整流程入口 |
| `reports/period_generator.py` | 飞书/企微卡片生成 + 推送 |
| `analyzers/period_ai.py` | 周报 AI 分析 |
| `analyzers/video_ai.py` | 视频 AI 分析 |
| `database/competitor_db.py` | 数据库操作层 |
