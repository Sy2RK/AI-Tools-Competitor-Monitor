"""
视频 AI 分析模块
使用多模态大模型分析 YouTube 视频内容（常规视频 + Shorts）

分析策略：
1. DashScope API + video_url（直接分析视频，需 DASHSCOPE_API_KEY）
   - YouTube URL → yt-dlp 下载（支持代理） → base64 编码 → 传入模型
   - 视频文件 > 7MB 时自动用 ffmpeg 压缩至 7MB 以下再分析
   - DashScope 服务器无法直接访问 YouTube，需本地下载后转 base64

代理配置：
- 在 .env 中设置 VIDEO_DOWNLOAD_PROXY（如 socks5://127.0.0.1:7890 或 http://127.0.0.1:7890）
- yt-dlp 和 requests 均会使用此代理下载视频

默认模型：
- DashScope: qwen3.6-plus（支持 video_url，支持视频直分析）
"""
import base64
import json
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI

import env_loader  # noqa: F401


# ===== API 配置 =====
DASHSCOPE_KEY = os.getenv("DASHSCOPE_API_KEY", "")

DEFAULT_TIMEOUT = float(os.environ.get("VIDEO_AI_TIMEOUT", "180"))  # 视频分析需要更长超时

# 视频下载代理（用于访问被墙的 googlevideo.com）
VIDEO_DOWNLOAD_PROXY = os.getenv("VIDEO_DOWNLOAD_PROXY", "").strip()

# DashScope 客户端（主方案：视频直分析）
dashscope_client = OpenAI(
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=DASHSCOPE_KEY,
    timeout=DEFAULT_TIMEOUT,
) if DASHSCOPE_KEY else None

# 视频分析模型（统一使用 qwen3.6-plus）
_DASHSCOPE_VIDEO_MODEL = "qwen3.6-plus"

# DashScope qwen3.6-plus 的 data-uri 限制为 10MB
# base64 编码会使数据膨胀约 33%，因此原始视频文件上限为 10 / 1.33 ≈ 7.5MB
_MAX_VIDEO_SIZE_MB = 7

# 视频缓存最大文件大小（MB），超过此大小不缓存
_MAX_CACHE_SIZE_MB = 50


def _get_dashscope_video_model() -> str:
    """获取 DashScope 视频分析模型"""
    return (os.getenv("DASHSCOPE_VIDEO_MODEL") or "").strip() or _DASHSCOPE_VIDEO_MODEL


def _get_ffmpeg_path() -> Optional[str]:
    """获取 ffmpeg 可执行文件路径（优先 imageio-ffmpeg，其次系统 ffmpeg）"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    # 尝试系统 ffmpeg
    import shutil
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    return None


def build_video_analysis_prompt(post: Dict[str, Any]) -> str:
    """
    构建视频分析 Prompt
    
    Args:
        post: 视频帖子数据（包含 text, description, engagement 等）
    
    Returns:
        分析 Prompt 字符串
    """
    title = post.get("text", "")
    description = post.get("description", "")
    is_short = post.get("is_short", False)
    video_type = "Shorts 短视频" if is_short else "常规视频"
    views = post.get("engagement", {}).get("view", 0)
    likes = post.get("engagement", {}).get("like", 0)
    duration = post.get("duration", "")
    duration_seconds = post.get("duration_seconds", 0)
    
    prompt = f"""你是一位 AI 产品竞品分析专家。请观看这个 YouTube {video_type}，从竞品监控角度进行简要分析。

## 视频基本信息
- 标题：{title}
- 类型：{video_type}
- 时长：{duration}（{duration_seconds}秒）
- 播放量：{views}，点赞数：{likes}
- 描述：{description[:300] if description else "无"}

## 分析要求
请简要分析视频内容，只返回以下两个字段，JSON 格式：

{{
    "video_summary": "一句话摘要：视频展示了什么内容（30字以内）",
    "competitive_insight": "一句话分析：这个视频反映了该产品的什么竞争策略或新动向（30字以内）"
}}

注意：
1. 每个字段严格控制在30字以内，不要啰嗦
2. 如果视频无法播放或内容不清晰，请在 video_summary 中说明
"""
    return prompt


def _extract_video_id(video_url: str) -> Optional[str]:
    """
    从 YouTube URL 中提取 video_id
    
    Args:
        video_url: YouTube 视频 URL
    
    Returns:
        video_id（11位字符串），解析失败返回 None
    """
    import re
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, video_url)
        if m:
            return m.group(1)
    return None


def _get_video_cache_dir() -> str:
    """获取视频缓存目录路径，不存在则创建"""
    # 使用项目根目录下的 cache/videos/
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(project_root, "cache", "videos")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _compress_video_with_ffmpeg(input_path: str, target_size_mb: float = 6.0) -> Optional[str]:
    """
    使用 ffmpeg 压缩视频文件至目标大小以下
    
    策略：降低分辨率（480p）+ 降低码率，确保压缩后文件 < target_size_mb
    
    Args:
        input_path: 输入视频文件路径
        target_size_mb: 目标文件大小（MB），默认 6MB（留余量给 base64 膨胀）
    
    Returns:
        压缩后的临时文件路径，失败返回 None
    """
    ffmpeg_path = _get_ffmpeg_path()
    if not ffmpeg_path:
        print(f"  ⚠️ ffmpeg 不可用，无法压缩视频")
        return None
    
    try:
        # 创建临时输出文件
        tmp_dir = tempfile.mkdtemp(prefix="ytb_compress_")
        output_path = os.path.join(tmp_dir, "compressed.mp4")
        
        # 使用 480p + 低码率压缩
        cmd = [
            ffmpeg_path,
            "-i", input_path,
            "-b:v", "200k",
            "-b:a", "48k",
            "-vf", "scale=480:-2",
            "-y",  # 覆盖输出
            output_path,
        ]
        
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        
        if result.returncode != 0:
            print(f"  ⚠️ ffmpeg 压缩失败: {result.stderr[:200]}")
            return None
        
        if not os.path.exists(output_path):
            return None
        
        compressed_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"  🗜️ 视频压缩完成: {compressed_size_mb:.1f}MB (目标 < {target_size_mb}MB)")
        
        if compressed_size_mb > target_size_mb:
            # 仍然太大，尝试更激进的压缩
            cmd_aggressive = [
                ffmpeg_path,
                "-i", input_path,
                "-b:v", "100k",
                "-b:a", "32k",
                "-vf", "scale=360:-2",
                "-y",
                output_path,
            ]
            result2 = subprocess.run(
                cmd_aggressive, capture_output=True, text=True, timeout=120
            )
            if result2.returncode == 0 and os.path.exists(output_path):
                compressed_size_mb = os.path.getsize(output_path) / (1024 * 1024)
                print(f"  🗜️ 二次压缩完成: {compressed_size_mb:.1f}MB")
        
        return output_path
    
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ ffmpeg 压缩超时")
        return None
    except Exception as exc:
        print(f"  ⚠️ ffmpeg 压缩异常: {exc}")
        return None


def _download_video_as_base64(video_url: str) -> Optional[str]:
    """
    使用 yt-dlp 下载视频并转为 base64 编码
    
    同时将视频源文件缓存到 cache/videos/{video_id}.mp4
    
    行为：
    - 始终下载视频并缓存到本地
    - 视频文件 ≤ 7MB 时：直接转 base64 返回
    - 视频文件 > 7MB 时：用 ffmpeg 压缩后转 base64 返回（确保始终走视频分析）
    
    支持通过 VIDEO_DOWNLOAD_PROXY 环境变量配置代理，
    用于访问被墙的 googlevideo.com CDN
    
    Args:
        video_url: YouTube 视频 URL
    
    Returns:
        base64 data URL（如 data:video/mp4;base64,...），失败返回 None
    """
    try:
        import yt_dlp
    except ImportError:
        print(f"  ⚠️ yt-dlp 未安装，无法下载视频")
        return None
    
    # 检查缓存中是否已有该视频
    video_id = _extract_video_id(video_url)
    cache_dir = _get_video_cache_dir()
    if video_id:
        # 查找缓存文件（可能是 mp4 或 webm）
        for ext in ["mp4", "webm", "mkv"]:
            cached_path = os.path.join(cache_dir, f"{video_id}.{ext}")
            if os.path.exists(cached_path):
                file_size_mb = os.path.getsize(cached_path) / (1024 * 1024)
                print(f"  💾 使用缓存视频: {video_id}.{ext} ({file_size_mb:.1f}MB)")
                
                if file_size_mb <= _MAX_VIDEO_SIZE_MB:
                    # 直接读取并转 base64
                    with open(cached_path, "rb") as f:
                        video_data = f.read()
                    b64 = base64.b64encode(video_data).decode("utf-8")
                    mime_type = f"video/{ext}" if ext != "webm" else "video/webm"
                    return f"data:{mime_type};base64,{b64}"
                else:
                    # 超大视频：用 ffmpeg 压缩后转 base64
                    print(f"  🗜️ 视频过大 ({file_size_mb:.1f}MB > {_MAX_VIDEO_SIZE_MB}MB)，使用 ffmpeg 压缩...")
                    compressed_path = _compress_video_with_ffmpeg(cached_path)
                    if compressed_path:
                        try:
                            with open(compressed_path, "rb") as f:
                                video_data = f.read()
                            b64 = base64.b64encode(video_data).decode("utf-8")
                            return f"data:video/mp4;base64,{b64}"
                        finally:
                            # 清理压缩临时文件
                            try:
                                import shutil
                                shutil.rmtree(os.path.dirname(compressed_path), ignore_errors=True)
                            except Exception:
                                pass
                    # ffmpeg 压缩失败，返回 None
                    print(f"  ⚠️ 视频压缩失败，无法分析此视频")
                    return None
    
    tmp_dir = tempfile.mkdtemp(prefix="ytb_video_")
    tmp_file = os.path.join(tmp_dir, "video.%(ext)s")
    
    try:
        ydl_opts = {
            "format": "worst[ext=mp4]/worst",  # 优先 mp4，最小质量
            "quiet": True,
            "no_warnings": True,
            "outtmpl": tmp_file,
            "overwrites": True,
            "socket_timeout": 30,
            "retries": 2,
            # 使用 android player_client 绕过 403 Forbidden（web client 会被拒绝下载）
            "extractor_args": {"youtube": {"player_client": ["android"]}},
        }
        
        # 配置代理（用于访问被墙的 googlevideo.com）
        if VIDEO_DOWNLOAD_PROXY:
            ydl_opts["proxy"] = VIDEO_DOWNLOAD_PROXY
            print(f"  🔀 使用代理: {VIDEO_DOWNLOAD_PROXY}")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get("ext", "mp4")
            filepath = os.path.join(tmp_dir, f"video.{ext}")
            
            if not os.path.exists(filepath):
                return None
            
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"  📥 视频下载完成 ({file_size_mb:.1f}MB)")
            
            # 缓存视频源文件到 cache/videos/{video_id}.{ext}
            if video_id and file_size_mb <= _MAX_CACHE_SIZE_MB:
                import shutil
                cached_path = os.path.join(cache_dir, f"{video_id}.{ext}")
                shutil.copy2(filepath, cached_path)
                print(f"  💾 视频已缓存: cache/videos/{video_id}.{ext}")
            
            if file_size_mb <= _MAX_VIDEO_SIZE_MB:
                # 直接转 base64
                with open(filepath, "rb") as f:
                    video_data = f.read()
                b64 = base64.b64encode(video_data).decode("utf-8")
                mime_type = f"video/{ext}" if ext != "webm" else "video/webm"
                data_url = f"data:{mime_type};base64,{b64}"
                return data_url
            else:
                # 超大视频：用 ffmpeg 压缩后转 base64
                print(f"  🗜️ 视频过大 ({file_size_mb:.1f}MB > {_MAX_VIDEO_SIZE_MB}MB)，使用 ffmpeg 压缩...")
                compressed_path = _compress_video_with_ffmpeg(filepath)
                if compressed_path:
                    try:
                        with open(compressed_path, "rb") as f:
                            video_data = f.read()
                        b64 = base64.b64encode(video_data).decode("utf-8")
                        return f"data:video/mp4;base64,{b64}"
                    finally:
                        # 清理压缩临时文件
                        try:
                            import shutil
                            shutil.rmtree(os.path.dirname(compressed_path), ignore_errors=True)
                        except Exception:
                            pass
                # ffmpeg 压缩失败，返回 None
                print(f"  ⚠️ 视频压缩失败，无法分析此视频")
                return None
    
    except Exception as exc:
        print(f"  ⚠️ 视频下载失败: {exc}")
        return None
    
    finally:
        # 清理临时文件
        try:
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


def analyze_video_by_url(
    video_url: str,
    post: Dict[str, Any],
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    分析视频内容
    
    分析策略：DashScope API + video_url（下载视频 → base64 → 直接分析视频内容）
    超大视频自动压缩后分析，不回退到纯文本。
    
    Args:
        video_url: 视频 URL（YouTube watch/shorts URL）
        post: 视频帖子元数据
        model: 指定模型（可选）
    
    Returns:
        分析结果字典
    """
    if not DASHSCOPE_KEY:
        print("⚠️ 未配置 DASHSCOPE_API_KEY，视频分析将被跳过。")
        return {}
    
    prompt = build_video_analysis_prompt(post)
    
    # ===== DashScope + video_url（下载视频 → base64） =====
    if dashscope_client:
        print(f"  🎥 [Video AI] 下载视频并分析...")
        video_data_url = _download_video_as_base64(video_url)
        if video_data_url:
            result = _analyze_via_dashscope_video(video_data_url, prompt, model)
            if result:
                return result
        print(f"  ⚠️ 视频分析失败（视频下载或模型调用失败）")
    else:
        print("⚠️ DashScope 客户端未初始化（缺少 DASHSCOPE_API_KEY）")
    
    return {}


def _analyze_via_dashscope_video(
    video_data_url: str,
    prompt: str,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 DashScope API 通过 video_url（base64）直接分析视频
    
    Args:
        video_data_url: base64 data URL（data:video/mp4;base64,...）
        prompt: 分析 Prompt
        model: 指定模型
    
    Returns:
        分析结果字典，失败返回空字典
    """
    current_model = model or _get_dashscope_video_model()
    
    for attempt in range(2):
        try:
            print(f"  🎥 [DashScope] 使用模型 {current_model} 分析视频...")
            
            content_parts = [
                {"type": "video_url", "video_url": {"url": video_data_url}},
                {"type": "text", "text": prompt}
            ]
            
            resp = dashscope_client.chat.completions.create(
                model=current_model,
                messages=[{"role": "user", "content": content_parts}],
                response_format={"type": "json_object"},
                timeout=DEFAULT_TIMEOUT,
            )
            
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                if attempt < 1:
                    print(f"  [WARN] DashScope 返回空响应，重试 {attempt+1}/2")
                    time.sleep(3)
                    continue
                return {}
            
            try:
                result = json.loads(content)
                print(f"  ✓ [DashScope] 视频分析完成（模型: {current_model}）")
                return result
            except json.JSONDecodeError:
                if "```" in content:
                    start = content.find("```")
                    start = content.find("\n", start) + 1 if content.find("\n", start) >= 0 else start + 3
                    end = content.rfind("```")
                    if end > start:
                        try:
                            result = json.loads(content[start:end].strip())
                            print(f"  ✓ [DashScope] 视频分析完成（模型: {current_model}）")
                            return result
                        except json.JSONDecodeError:
                            pass
                if attempt < 1:
                    print(f"  [WARN] JSON 解析失败，重试 {attempt+1}/2")
                    time.sleep(3)
                    continue
                return {}
                
        except Exception as exc:
            error_str = str(exc).lower()
            if "video" in error_str and ("not support" in error_str or "unsupported" in error_str):
                print(f"  ⚠️ DashScope 模型 {current_model} 不支持视频输入")
                return {}
            
            if attempt < 1:
                print(f"  [WARN] DashScope 调用失败，重试 {attempt+1}/2: {exc}")
                time.sleep(3 * (attempt + 1))
            else:
                print(f"  [WARN] DashScope 调用失败: {exc}")
    
    return {}


def analyze_youtube_posts(
    posts: List[Dict[str, Any]],
    max_posts: int = 5
) -> List[Dict[str, Any]]:
    """
    批量分析 YouTube 视频帖子
    
    为每个视频帖子添加 video_analysis 字段
    
    Args:
        posts: 视频帖子列表（来自 get_recent_videos）
        max_posts: 最多分析多少条（避免 API 调用过多）
    
    Returns:
        添加了 video_analysis 字段的帖子列表
    """
    if not DASHSCOPE_KEY:
        print("⚠️ 未配置 DASHSCOPE_API_KEY，跳过视频分析")
        return posts
    
    analyzed = 0
    for post in posts:
        if analyzed >= max_posts:
            break
        
        post_url = post.get("post_url", "")
        if not post_url:
            continue
        
        print(f"  🎥 分析视频: {post.get('text', '')[:50]}...")
        
        try:
            analysis = analyze_video_by_url(post_url, post)
            if analysis:
                post["video_analysis"] = analysis
                analyzed += 1
            else:
                post["video_analysis"] = None
        except Exception as exc:
            print(f"  ⚠️ 视频分析异常: {exc}")
            post["video_analysis"] = None
        
        # 避免 API 限流
        if analyzed < max_posts:
            time.sleep(2)
    
    if analyzed > 0:
        print(f"  ✓ 完成 {analyzed}/{min(len(posts), max_posts)} 条视频分析")
    
    return posts


def main():
    """命令行入口：测试视频分析"""
    import argparse
    
    parser = argparse.ArgumentParser(description="YouTube 视频分析测试")
    parser.add_argument("--url", type=str, help="YouTube 视频 URL")
    parser.add_argument("--model", type=str, help="指定模型")
    parser.add_argument("--days-ago", type=int, default=7, help="获取最近多少天的视频")
    parser.add_argument("--company", type=str, default="PixVerse", help="测试公司名")
    args = parser.parse_args()
    
    if args.url:
        # 直接分析指定 URL
        print(f"🎥 分析视频: {args.url}")
        post = {"text": "手动测试", "description": "", "is_short": False, "engagement": {}}
        result = analyze_video_by_url(args.url, post, model=args.model)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # 从 YouTube API 获取视频后分析
        from scrapers.youtube_official import is_api_available, get_channel_id_by_handle, get_recent_videos
        
        if not is_api_available():
            print("❌ YOUTUBE_API_KEY 未配置")
            return
        
        print(f"🎥 获取 {args.company} 的 YouTube 视频并分析...")
        
        # 测试用 handle
        test_handles = {
            "PixVerse": "PixVerse_Official",
            "AI Mirror": "AIMirror",
            "AI Marvels": "HitPaw",
        }
        handle = test_handles.get(args.company, args.company)
        
        channel_id = get_channel_id_by_handle(handle)
        if not channel_id:
            print(f"❌ 无法解析 handle: {handle}")
            return
        
        posts = get_recent_videos(channel_id, days_ago=args.days_ago)
        if not posts:
            print("❌ 未获取到视频")
            return
        
        # 分析第一条视频
        print(f"\n🎥 分析第一条视频: {posts[0].get('text', '')[:50]}...")
        result = analyze_video_by_url(posts[0]["post_url"], posts[0], model=args.model)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
