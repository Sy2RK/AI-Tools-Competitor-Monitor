# AI 产品竞品社媒监控

这个小工具帮你做两件事：

1. **每天**：自动去 AI 竞品的社交账号和官网上，把新发的内容抓下来，存进电脑里的一个数据库文件（就是一个 `db` 文件夹里的 `.db` 文件，用记事本打不开也没关系，程序会读）。
2. **每周（或任意几天）**：把这段时间里抓到的内容交给 AI 看一眼，写一份**竞品周报**，可以发到飞书或企业微信；不想发也可以只生成文件。

你只要搞清楚：**竞品名单和账号写在哪、每天怎么跑、周报怎么跑**，就够了。

---

## 先装好 Python 环境（只做一次）

在项目文件夹里打开终端，依次执行：

```bash
python -m venv .venv
source .venv/bin/activate
```

（Windows 电脑把第二行改成：`.venv\Scripts\activate`）

再装依赖：

```bash
pip install -r requirements.txt
```

---

## 配置写在哪？

### ① 竞品名单和各个平台账号——改 `config/config.yaml`

打开 **`config/config.yaml`**，找到最上面的 **`competitors`** 这一块。

- 这里列出**要监控的 AI 产品**，每个产品下面写**各平台账号**（TikTok、Instagram、Twitter/X、YouTube、官网等）。
- **日常爬数据，程序只认这里。**
  改完保存，下次跑爬虫就会按新的来。
- 如果你有竞品名单的 CSV 文件，可以用 `scripts/csv_to_config.py` 自动生成 `config.yaml`。

### ② 密钥和机器人地址——改项目根目录的 `.env`

在项目根目录放一个 **`.env`** 文件（和 `README.md` 同级），里面放一些**密码一样的东西**，不要发给陌生人，也不要上传到公开的网盘。

常用项举例：

| 要写什么 | 干什么用 |
|----------|----------|
| `RAPIDAPI_KEY` | 去 RapidAPI 上抓 TikTok、Instagram、Twitter/X 等用的钥匙 |
| `YOUTUBE_API_KEY` | （可选）Google YouTube Data API v3 钥匙，填了优先用官方 API（精确时间戳 + Shorts），不填则降级到 RapidAPI |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API 钥匙，用于视频 AI 分析（qwen3.6-plus 模型） |
| `VIDEO_DOWNLOAD_PROXY` | （可选）视频下载代理，用于访问被墙的 googlevideo.com（如 `socks5://127.0.0.1:7890`） |
| `VIDEO_ANALYSIS_MAX_POSTS` | （可选）每次视频AI分析最多分析几条视频，默认 5 |
| `OPENROUTER_API_KEY`（或 `OPENAI_API_KEY`） | 写周报时 AI 用的钥匙 |
| `FEISHU_WEBHOOK_URL` | 飞书群里机器人的地址，填了才会往飞书发周报 |
| `WEWORK_WEBHOOK_URL` | 企业微信同理 |
| `JINA_API_KEY` | （可选）官网爬虫 Jina Reader 用的钥匙，免费额度通常够用 |

飞书、企微也可以在 **`config/config.yaml`** 里 `notification` 那一段写，但很多人习惯全放在 `.env`，二选一、别重复泄露就行。

---

## 支持的平台

| 平台 | 数据来源 | 说明 |
|------|----------|------|
| TikTok | RapidAPI | 抓取用户帖子（短视频） |
| Instagram | RapidAPI | 抓取用户帖子（图片/视频/Reels） |
| Twitter/X | RapidAPI | 抓取用户推文 |
| YouTube | 官方 API 优先 + RapidAPI 降级 | 配置 `YOUTUBE_API_KEY` 后：精确时间戳 + Shorts 支持；未配置则降级到 RapidAPI（无精确时间戳，Shorts 不支持） |
| Website | 混合爬虫 | RSS 优先 → Jina Reader → Requests 降级 |

---

## 第一件事：每天抓一次数据

含义：**把「昨天」竞品新发的东西抓进数据库**（也可以改成别的日期，下面有说明）。

在项目根目录执行（先进入虚拟环境 `source .venv/bin/activate`）：

```bash
export PYTHONPATH="$(pwd):$PYTHONPATH"
python scrapers/daily_scraper.py --days-ago 1
```

- `--days-ago 1` 表示**昨天**。想抓**今天**就改成 `0`。
- 只想抓某几个产品，可以加：`--companies "PixVerse" "AI Mirror"`（名字要和 `config.yaml` 里写的一样）。

苹果电脑上也可以直接双击跑脚本同目录下的 **`run-daily-scraper.sh`**（它会尝试自动用 `.venv`）。

---

## 第二件事：生成竞品周报

含义：**选定一段日期**（例如上周一到上周日），把这段时间数据库里已有的内容提出来 → AI 分析 → 出周报。

```bash
export PYTHONPATH="$(pwd):$PYTHONPATH"
python workflows/period_workflow.py --start-date 2026-04-01 --end-date 2026-04-07
```

把日期换成你真正要总结的那几天。**开始、结束两天都算在内。**

- 只想在电脑上生成文件、**不要发到飞书/企微**，后面加：`--skip-send`
- 只想做某几个产品：`--companies 产品名`

定时每周跑一次的话，可以看 **`run-weekly-period-workflow.sh`** 和 **`setup-weekly-cron.sh`** 里的说明（适合会一点命令行的人）。

---

## 文件夹大概都是啥（想深究再看）

| 位置 | 白话 |
|------|------|
| `config/config.yaml` | 竞品名单 + 各平台账号 + 可选：推送用的网址 |
| `db/competitor_data.db` | 抓下来的内容和周报缓存，都在这个本地数据库里 |
| `scrapers/` | 每天爬内容用的程序（含官网混合爬虫） |
| `workflows/` | 周报一整条流程；里面的 `output` 文件夹会临时放一些中间文件 |
| `reports/`、`analyzers/` | 周报：从数据库里取数、让 AI 写、排版发送 |
| `scripts/` | 辅助脚本（CSV→YAML 转换等） |
| `plans/` | 改造方案文档 |

---

## 许可证

详见项目里的 **`LICENSE`** 文件。
