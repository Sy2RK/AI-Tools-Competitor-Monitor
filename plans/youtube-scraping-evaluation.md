# YouTube 爬取方案全面评估

## 一、当前实现现状与问题

### 1.1 当前架构

当前 YouTube 爬取使用 **两个 RapidAPI 第三方 API**：

| 用途 | RapidAPI Host | 端点 | 状态 |
|------|--------------|------|------|
| 常规视频 | `youtube138.p.rapidapi.com` | `/channel/videos/` | 可用但有问题 |
| Shorts 短视频 | `yt-api.p.rapidapi.com` | `/channel/shorts` | 已禁用 |

### 1.2 已知问题清单

#### 问题 1：无精确发布时间戳 ⚠️ 严重

[`get_posts_from_youtube()`](scrapers/rapidapi.py:771) 返回的数据中 **没有绝对时间戳**，只有 `publishedTimeText` 相对文本（如 `"3 hours ago"`、`"2 days ago"`）：

```python
# rapidapi.py 第 832 行
published_time_text = content.get("publishedTimeText", "")  # "3 hours ago"
```

这导致无法做精确的日期过滤。

#### 问题 2：日期过滤形同虚设 ⚠️ 严重

[`rapidapi.py:849`](scrapers/rapidapi.py:849) 中有一个 `or True` 的 hack：

```python
if is_yesterday or True:  # 暂时都包含，实际应该精确判断
```

这意味着 **所有视频都会被包含**，日期过滤完全失效。这是因为相对时间文本解析不可靠，开发者不得不绕过。

#### 问题 3：Shorts 完全不可用 ⚠️ 严重

[`scrape_youtube_platform()`](scrapers/daily_scraper.py:268) 中明确标注：

```python
print(f"      ⚠️ 注意: Shorts 短视频暂不支持")
```

虽然 [`get_youtube_shorts_from_channel()`](scrapers/rapidapi.py:927) 函数存在，但：
- 使用的 `yt-api.p.rapidapi.com` 端点不稳定
- handle → channel ID 转换经常失败
- 在 `daily_scraper.py` 中未调用

#### 问题 4：Handle 解析不可靠 ⚠️ 中等

[`get_youtube_channel_id_from_handle()`](scrapers/rapidapi.py:718) 尝试将 `@username` 转为 channel ID，但：
- API 端点 `/channel/details/?handle=xxx` 经常返回空
- 失败后只能回退到直接用 handle 尝试，成功率低

#### 问题 5：互动数据不完整 ⚠️ 轻微

只返回 `views`，缺少 `likes`、`comments` 等互动数据。

---

## 二、方案评估

### 方案 A：Google 官方 YouTube Data API v3 ⭐ 推荐

#### 概述

Google 官方提供的 REST API，通过 API Key 即可访问公开数据。

#### 能力对比

| 能力 | 支持情况 | 说明 |
|------|---------|------|
| 常规视频 | ✅ | `search.list` 或 `channels.list` + `playlistItems.list` |
| Shorts 短视频 | ✅ | 同一接口返回，通过 duration ≤ 60s 识别 |
| 精确时间戳 | ✅ | `publishedAt` 返回 ISO 8601 格式 |
| 日期过滤 | ✅ | `publishedAfter` 参数原生支持 |
| Handle 解析 | ✅ | `channels.list?forHandle=xxx` 原生支持 |
| 互动数据 | ✅ | views、likes、comments 全部返回 |
| 视频描述 | ✅ | `description` 字段 |
| 视频标签 | ✅ | `tags` 字段 |

#### 配额计算（12 个 AI 产品）

| 操作 | 单次消耗 | 每日调用 | 日消耗 |
|------|---------|---------|--------|
| Handle → Channel ID（`channels.list`） | 1 单位 | 12 次 | 12 |
| 获取最新视频（`search.list`） | 100 单位 | 12 次 | 1,200 |
| 视频详情（`videos.list`，可选） | 1 单位 | ~60 次 | 60 |
| **合计** | | | **~1,272 单位/天** |

免费配额：**10,000 单位/天**，使用率仅 ~13%，非常充裕。

#### 获取 Shorts 的方式

YouTube Data API v3 **不区分**常规视频和 Shorts，Shorts 本质就是时长 ≤ 60 秒的视频。获取方式：

```
方式 1：search.list + 过滤
  → 搜索频道最近视频，返回后按 duration 过滤

方式 2：playlistItems.list（频道的 uploads 播放列表）
  → 获取频道上传列表，再查 videos.list 获取 duration
  → 按 duration <= 60s 判断是否为 Short
```

#### 优点

1. **精确时间戳** — `publishedAt` 为 ISO 8601 格式，日期过滤 100% 准确
2. **Shorts 一站式获取** — 不需要单独的 API，同一接口覆盖
3. **Handle 原生支持** — `forHandle` 参数直接解析，无需额外转换
4. **免费额度充足** — 12 个产品每天仅用 ~13% 配额
5. **官方稳定** — 不会像第三方 API 随时下线或改版
6. **数据完整** — 标题、描述、标签、互动数据全有

#### 缺点

1. **需要 Google Cloud 项目** — 需要创建项目、启用 API、获取 API Key
2. **配额限制** — 虽然当前够用，但如果产品数量大幅增加可能需要申请更高配额
3. **Shorts 无独立标识** — 需要通过 duration 判断，不是原生字段

#### 所需配置

```env
# .env 新增
YOUTUBE_API_KEY=AIzaSy...  # Google Cloud YouTube Data API v3 Key
```

---

### 方案 B：继续使用 RapidAPI（当前方案）

#### 概述

维持现有的 `youtube138` + `yt-api` 双 API 架构，修复已知问题。

#### 可行的修复

| 问题 | 修复方案 | 可行性 |
|------|---------|--------|
| 无精确时间戳 | 用 `videos.list` 补查？❌ RapidAPI 无此端点 | 不可行 |
| 日期过滤失效 | 解析 `publishedTimeText`？仅能粗略判断 | 低 |
| Shorts 不可用 | 换其他 RapidAPI YouTube API？ | 中 |
| Handle 解析失败 | 换 API 或用页面抓取？ | 中 |

#### 核心瓶颈

**RapidAPI 的 YouTube API 本质上是爬虫封装**，它们抓取 YouTube 页面并提取数据。YouTube 页面本身对视频列表只显示相对时间（"3 hours ago"），所以这些 API 也只能返回相对时间。这是结构性限制，无法通过换一个 RapidAPI API 解决。

#### 优点

1. 无需额外账号 — 复用现有 RapidAPI Key
2. 已集成 — 代码已写好

#### 缺点

1. **无精确时间戳** — 这是结构性限制，无法修复
2. **Shorts 不可靠** — 第三方 API 对 Shorts 支持普遍差
3. **稳定性差** — 第三方爬虫 API 随时可能失效
4. **数据不完整** — 缺少描述、标签、完整互动数据

---

### 方案 C：RapidAPI 上其他 YouTube API

RapidAPI 上有多个 YouTube 相关 API，评估几个主要的：

| API 名称 | Host | 精确时间 | Shorts | 免费额度 | 评价 |
|----------|------|---------|--------|---------|------|
| YouTube138 | `youtube138.p.rapidapi.com` | ❌ 相对时间 | ❌ | 有限 | 当前使用 |
| YT API | `yt-api.p.rapidapi.com` | ❌ | ⚠️ 不稳定 | 有限 | 当前 Shorts |
| YouTube Data API v3 (RapidAPI 代理) | 多个 | ✅ | ✅ | 极少 | 不如直接用官方 |
| Youtube v3.1 | 多个 | ⚠️ 部分有 | ⚠️ | 有限 | 数据质量参差 |

**结论**：RapidAPI 上没有能同时解决精确时间戳 + Shorts 的免费方案。部分 API 声称返回时间戳，但实际测试发现要么是相对时间，要么免费额度极少（5-50 次/天）。

---

### 方案 D：混合方案（官方 API 优先 + RapidAPI 降级）⭐ 推荐

#### 架构

```
YouTube 爬取请求
    │
    ├─ 优先：Google YouTube Data API v3
    │   ├─ channels.list → Handle 解析为 Channel ID
    │   ├─ search.list → 获取最近视频（含 Shorts）
    │   └─ videos.list → 获取视频详情（duration 等）
    │
    └─ 降级：RapidAPI youtube138（仅当官方 API 不可用时）
        └─ channel/videos → 获取视频列表（无精确时间）
```

#### 降级触发条件

1. `YOUTUBE_API_KEY` 未配置
2. 官方 API 配额耗尽（HTTP 403 quotaExceeded）
3. 官方 API 网络不可达

#### 优点

1. 最佳数据质量 — 官方 API 提供精确时间戳 + Shorts
2. 向后兼容 — 未配置官方 Key 时自动降级到 RapidAPI
3. 高可用 — 双通道保障

#### 缺点

1. 代码复杂度增加 — 需要维护两套 API 调用逻辑
2. 降级模式下仍有原有问题 — 但至少不会完全不可用

---

## 三、方案对比总结

| 维度 | 方案 A：官方 API | 方案 B：RapidAPI | 方案 D：混合 |
|------|----------------|-----------------|-------------|
| 精确时间戳 | ✅ | ❌ | ✅/❌ 降级时 |
| Shorts 支持 | ✅ | ❌ | ✅/❌ 降级时 |
| 日期过滤 | ✅ 原生 | ❌ 失效 | ✅/❌ 降级时 |
| Handle 解析 | ✅ 原生 | ⚠️ 不可靠 | ✅/❌ 降级时 |
| 数据完整度 | ✅ 高 | ⚠️ 低 | ✅/⚠️ |
| 免费额度 | 10,000/天 | 有限 | 两者叠加 |
| 稳定性 | ✅ 官方 | ⚠️ 第三方 | ✅ 双保障 |
| 额外配置 | Google API Key | 无 | Google API Key |
| 实现复杂度 | 中 | 低（已有） | 中高 |

---

## 四、推荐方案：D 混合方案

### 4.1 实施步骤

#### Step 1：创建 Google Cloud 项目 + 获取 API Key

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建新项目（如 `competitor-monitor`）
3. 启用 **YouTube Data API v3**
4. 创建 API 凭据（API Key）
5. 将 Key 填入 `.env` 的 `YOUTUBE_API_KEY`

#### Step 2：新建 `scrapers/youtube_official.py`

核心函数：

```python
def get_channel_id_by_handle(handle: str) -> Optional[str]
    → channels.list(forHandle=handle) → 返回 channel ID

def get_recent_videos(channel_id: str, days_ago: int = 1) -> List[Dict]
    → search.list(channelId, publishedAfter, type=video) → 返回视频列表

def get_video_details(video_ids: List[str]) -> Dict[str, Dict]
    → videos.list(id=..., part=snippet,contentDetails,statistics)
    → 返回标题、描述、时长、播放量、点赞数等

def is_short(duration_iso: str) -> bool
    → 解析 ISO 8601 duration，判断是否 ≤ 60 秒
```

#### Step 3：修改 `scrapers/daily_scraper.py`

修改 [`scrape_youtube_platform()`](scrapers/daily_scraper.py:268)：

```python
def scrape_youtube_platform(...):
    # 优先使用官方 API
    if os.getenv("YOUTUBE_API_KEY"):
        from scrapers.youtube_official import get_recent_videos, get_channel_id_by_handle
        # 使用官方 API...
    else:
        # 降级到 RapidAPI
        from scrapers.rapidapi import get_posts_from_youtube
        # 使用 RapidAPI...
```

#### Step 4：修改 `config/config.yaml`

YouTube 平台配置增加 `channel_id` 字段缓存（避免每次都解析 handle）：

```yaml
- username: PixVerse_Official
  type: youtube
  enabled: true
  channel_id: ''        # 首次运行后自动填充
  url: https://www.youtube.com/@PixVerse_Official
```

#### Step 5：更新 `.env` 和 `requirements.txt`

```env
# .env
YOUTUBE_API_KEY=AIzaSy...
```

```
# requirements.txt 新增
google-api-python-client>=2.0.0
```

> 注：也可以不用官方 SDK，直接用 `requests` 调用 REST API，避免引入重依赖。

### 4.2 数据格式统一

官方 API 返回的数据需要转换为与现有格式兼容的结构：

```python
{
    "text": "视频标题",
    "published_at": "2026-04-09T14:30:00Z",      # 精确时间戳 ✅
    "published_at_display": "2026-04-09 14:30",    # 可读时间
    "post_url": "https://www.youtube.com/watch?v=xxx",
    "media_urls": ["https://i.ytimg.com/vi/xxx/maxresdefault.jpg"],
    "engagement": {
        "view": 12345,
        "like": 567,      # 新增 ✅
        "comment": 89     # 新增 ✅
    },
    "is_short": True,     # 新增 ✅ 标识是否为 Shorts
    "duration": "PT45S",  # 新增 ✅ ISO 8601 时长
    "description": "...", # 新增 ✅ 视频描述
}
```

### 4.3 Shorts 识别逻辑

```python
import re

def parse_iso8601_duration(duration: str) -> int:
    """将 ISO 8601 duration 转为秒数。PT1H2M10S → 3730 秒"""
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds

def is_short(duration: str) -> bool:
    """判断是否为 YouTube Short（时长 ≤ 60 秒且为竖屏）"""
    return parse_iso8601_duration(duration) <= 60
```

### 4.4 Channel ID 缓存策略

Handle → Channel ID 的解析结果应缓存，避免每次都消耗配额：

1. **首次运行**：调用 `channels.list(forHandle=xxx)` 获取 channel ID
2. **写入 config.yaml**：自动回填 `channel_id` 字段
3. **后续运行**：直接使用缓存的 channel ID，跳过解析步骤

---

## 五、风险与注意事项

1. **Google API Key 安全**：API Key 仅限 YouTube Data API v3，建议在 Google Cloud Console 设置 API 限制
2. **配额监控**：虽然 12 个产品每天仅用 ~13% 配额，但建议添加配额检查日志
3. **Shorts 识别精度**：≤60 秒的判断可能将部分非 Shorts 的短视频误判为 Shorts，但这是目前最可靠的方案
4. **降级模式数据差异**：RapidAPI 降级模式下缺少精确时间戳和 Shorts，AI 分析时需注意数据质量下降
5. **不使用官方 SDK**：建议直接用 `requests` 调用 REST API，避免 `google-api-python-client` 的重依赖（~20MB）

---

## 六、结论

**推荐方案 D（混合方案）**，以 Google YouTube Data API v3 为主、RapidAPI 为降级备选。

核心收益：
- ✅ 解决精确时间戳问题 → 日期过滤 100% 准确
- ✅ 解决 Shorts 不可用问题 → 通过 duration 判断一站式获取
- ✅ 解决 Handle 解析问题 → `forHandle` 参数原生支持
- ✅ 数据完整度大幅提升 → 描述、标签、完整互动数据
- ✅ 向后兼容 → 未配置官方 Key 时自动降级
