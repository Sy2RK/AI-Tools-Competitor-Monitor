# AI 产品竞品社媒监控

自动监控 AI 竞品在各大社交平台和官网的动态，生成竞品周报推送到飞书/企业微信。

## 功能概览

1. **每日抓取**：自动爬取竞品在 TikTok、Instagram、Twitter/X、YouTube、官网的新发内容，存入本地数据库
2. **周报生成**：提取一段时间内的数据 → AI 分析 → 生成精简周报 → 推送到飞书/企业微信
3. **视频 AI 分析**：通过阿里云 DashScope（qwen3.6-plus）直接分析 YouTube 视频内容

---

## 快速开始

### 1. 安装 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置

#### ① 竞品名单和平台账号 → `config/config.yaml`

在 `config/config.yaml` 的 `competitors` 中配置要监控的 AI 产品及其各平台账号：

```yaml
competitors:
- name: PixVerse
  priority: high
  platforms:
  - username: pixverse
    type: tiktok
    enabled: true
    url: https://www.tiktok.com/@pixverse
  - username: pixverse_official
    type: instagram
    enabled: true
    url: https://www.instagram.com/pixverse_official/
  # ... 更多平台
```

支持的平台类型：`tiktok`、`instagram`、`twitter`、`youtube`、`website`

#### ② 密钥和推送地址 → `.env`

在项目根目录创建 `.env` 文件：

| 变量 | 必填 | 说明 |
|------|------|------|
| `RAPIDAPI_KEY` | ✅ | RapidAPI 密钥（TikTok/Instagram/Twitter 爬虫），支持多个 Key 用逗号分隔轮换 |
| `OPENROUTER_API_KEY` | ✅ | OpenRouter API 密钥（周报 AI 分析） |
| `YOUTUBE_API_KEY` | 推荐 | Google YouTube Data API v3 密钥，配置后优先使用官方 API |
| `DASHSCOPE_API_KEY` | 可选 | 阿里云 DashScope 密钥，用于视频 AI 分析 |
| `FEISHU_WEBHOOK_URL` | 可选 | 飞书群机器人 Webhook |
| `WEWORK_WEBHOOK_URL` | 可选 | 企业微信群机器人 Webhook |
| `VIDEO_DOWNLOAD_PROXY` | 可选 | 视频下载代理（如 `socks5://127.0.0.1:7890`） |
| `JINA_API_KEY` | 可选 | Jina Reader 密钥（官网爬虫增强） |

---

## 支持的平台

| 平台 | 数据来源 | 说明 |
|------|----------|------|
| TikTok | RapidAPI | 抓取用户帖子（短视频） |
| Instagram | RapidAPI | 抓取用户帖子（图片/视频/Reels） |
| Twitter/X | RapidAPI | 抓取用户推文 |
| YouTube | 官方 API 优先 + RapidAPI 降级 | 配置 `YOUTUBE_API_KEY` 后：精确时间戳 + Shorts 支持 |
| Website | 混合爬虫 | RSS 优先 → Jina Reader → Requests 降级 |

---

## 使用方法

### 每日抓取数据

```bash
export PYTHONPATH="$(pwd):$PYTHONPATH"
python scrapers/daily_scraper.py --days-ago 1
```

- `--days-ago 1`：抓取从昨天到现在的数据（默认）
- `--days-ago 7`：抓取最近 7 天
- `--companies "PixVerse" "AI Mirror"`：只抓指定产品

### 生成竞品周报

```bash
export PYTHONPATH="$(pwd):$PYTHONPATH"
python workflows/period_workflow.py --start-date 2026-04-10 --end-date 2026-04-16
```

- `--skip-send`：只生成文件，不推送到飞书/企微
- `--companies "PixVerse"`：只生成指定产品的周报
- `--send-to-wework`：同时推送到企业微信

### 周报内容

每份周报包含：
- **摘要**：AI 生成的该时间段竞品动态总结
- **相关链接**：最相关的 3 条帖子链接
- **视频分析**：YouTube 视频的一句话摘要 + 竞争策略分析（需配置 DashScope）

---

## 服务器部署

### 1. 安装依赖

```bash
# Python 环境
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 系统依赖（视频压缩需要 ffmpeg）
# Ubuntu/Debian:
sudo apt install ffmpeg
# macOS:
brew install ffmpeg
# ffmpeg 也可通过 imageio-ffmpeg 自动获取（无需系统安装）
```

### 2. 配置 `.env`

复制 `.env` 模板并填写密钥（详见上方"密钥和推送地址"表格）。

**⚠️ 服务器特别注意**：
- `VIDEO_DOWNLOAD_PROXY`：本地开发用的 `socks5://127.0.0.1:7890` 需改为服务器可用代理，海外服务器可留空
- `FEISHU_WEBHOOK_URL`：建议使用服务器专用的飞书群 Webhook

### 3. 安装定时任务

```bash
# 一键安装所有定时任务（推荐）
./setup-cron.sh
```

安装的定时任务：

| 任务 | 频率 | 说明 |
|------|------|------|
| 每日爬虫 | 每天 10:00 | 爬取前一天各平台数据 |
| 每周周报 | 每周一 10:30 | 生成过去7天竞品周报并推送 |
| 数据库备份 | 每天 02:00 | SQLite 数据库备份，保留最近 10 份 |
| 日志清理 | 每周日 03:00 | 清理 30 天前的日志、7 天前的视频缓存 |

也可单独安装：

```bash
./setup-daily-cron.sh       # 仅安装每日爬虫
./setup-weekly-cron.sh      # 仅安装每周周报
```

### 4. 运维脚本

```bash
# 手动备份数据库（默认保留 10 份）
./scripts/backup-db.sh
./scripts/backup-db.sh 20    # 保留 20 份

# 手动清理日志和缓存
./scripts/cleanup-logs.sh           # 默认：日志保留 30 天，视频缓存保留 7 天
./scripts/cleanup-logs.sh 60 14     # 日志保留 60 天，视频缓存保留 14 天
```

### 5. 目录说明

| 目录 | 用途 | 是否自动创建 |
|------|------|-------------|
| `db/` | SQLite 数据库 | 首次运行自动创建 |
| `db/backups/` | 数据库备份 | 备份脚本自动创建 |
| `logs/` | 运行日志 | shell 脚本自动创建 |
| `cache/videos/` | 视频缓存 | 首次下载自动创建 |

---

## 项目结构

```
├── config/config.yaml          # 竞品名单 + 各平台账号配置
├── .env                        # API 密钥和推送地址（勿提交）
├── db/competitor_data.db       # 本地数据库（抓取数据 + 周报缓存）
├── db/backups/                 # 数据库备份目录
├── logs/                       # 运行日志
├── cache/videos/               # 视频缓存
├── scrapers/                   # 爬虫模块
│   ├── daily_scraper.py        # 每日抓取入口
│   ├── rapidapi.py             # TikTok/Instagram/Twitter RapidAPI 爬虫
│   ├── youtube_official.py     # YouTube 官方 API 爬虫
│   └── website_scraper.py      # 官网混合爬虫（RSS + Jina + Requests）
├── analyzers/                  # AI 分析模块
│   ├── period_ai.py            # 周报 AI 分析（摘要 + 相关链接）
│   └── video_ai.py             # 视频 AI 分析（DashScope qwen3.6-plus）
├── reports/                    # 报告生成模块
│   ├── period_extractor.py     # 数据提取器
│   └── period_generator.py     # 飞书/企微卡片生成 + 推送
├── workflows/                  # 工作流
│   └── period_workflow.py      # 周报完整流程（提取→分析→报告→推送）
├── database/                   # 数据库模块
│   └── competitor_db.py        # SQLite 数据库操作
├── scripts/                    # 运维脚本
│   ├── backup-db.sh            # 数据库备份
│   └── cleanup-logs.sh         # 日志和缓存清理
├── setup-cron.sh               # 一键安装所有定时任务
├── setup-daily-cron.sh         # 安装每日爬虫定时任务
├── setup-weekly-cron.sh        # 安装每周周报定时任务
├── run-daily-scraper.sh        # 每日爬虫执行脚本
└── run-weekly-period-workflow.sh # 每周周报执行脚本
```

---

## 当前监控的 AI 产品（11 个）

PixVerse、AI Mirror、Glam AI、DreamFace、Creati、SelfyzAI、Momo、AI Marvels (HitPaw)、Revive、FacePlay、Hula AI

---

## 许可证

详见项目里的 `LICENSE` 文件。
