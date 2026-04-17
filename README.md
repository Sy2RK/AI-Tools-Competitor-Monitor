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
python workflows/period_workflow.py --start-date 2026-04-10 --end-date 2026-04-17
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

## 项目结构

```
├── config/config.yaml      # 竞品名单 + 各平台账号配置
├── .env                    # API 密钥和推送地址（勿提交）
├── db/competitor_data.db   # 本地数据库（抓取数据 + 周报缓存）
├── scrapers/               # 爬虫模块
│   ├── daily_scraper.py    # 每日抓取入口
│   ├── rapidapi.py         # TikTok/Instagram/Twitter RapidAPI 爬虫
│   ├── youtube_official.py # YouTube 官方 API 爬虫
│   └── website_scraper.py  # 官网混合爬虫（RSS + Jina + Requests）
├── analyzers/              # AI 分析模块
│   ├── period_ai.py        # 周报 AI 分析（摘要 + 相关链接）
│   └── video_ai.py         # 视频 AI 分析（DashScope qwen3.6-plus）
├── reports/                # 报告生成模块
│   ├── period_extractor.py # 数据提取器
│   └── period_generator.py # 飞书/企微卡片生成 + 推送
├── workflows/              # 工作流
│   └── period_workflow.py  # 周报完整流程（提取→分析→报告→推送）
└── database/               # 数据库模块
    └── competitor_db.py    # SQLite 数据库操作
```

---

## 当前监控的 AI 产品（12 个）

PixVerse、AI Mirror、Glam AI、DreamFace、Creati、SelfyzAI、Momo、Videa、AI Marvels (HitPaw)、Revive、FacePlay、Hula AI

---

## 许可证

详见项目里的 `LICENSE` 文件。
