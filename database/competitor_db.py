"""
竞品监控数据库（SQLite）
每个公司一张表，记录每个平台每天获取的 raw data
"""
import json
import os
import re
import sqlite3
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from pathlib import Path


class CompetitorDatabaseDB:
    """竞品历史数据库，使用 SQLite 存储，每个公司一张表"""
    
    def __init__(self, db_path: str = None):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径，默认为 db/competitor_data.db
        """
        if db_path is None:
            # 优先使用环境变量指定的目录
            db_dir = os.environ.get("COMPETITOR_DB_DIR")
            if db_dir and os.path.exists(db_dir):
                # 使用环境变量指定的目录
                pass
            else:
                # 默认使用项目根目录下的 db/ 目录
                # 获取项目根目录（database 目录的父目录）
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                db_dir = os.path.join(project_root, "db")
                # 如果项目根目录的 db 不存在，尝试 Docker 环境的 /app/db
                if not os.path.exists(db_dir):
                    docker_db_dir = "/app/db"
                    if os.path.exists(docker_db_dir):
                        db_dir = docker_db_dir
                    else:
                        # 都不存在，创建项目根目录下的 db
                        os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "competitor_data.db")
        
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # 初始化数据库（创建表等）
        self._init_database()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 使结果可以按列名访问
        return conn
    
    def _init_database(self):
        """初始化数据库，创建必要的表"""
        conn = self._get_connection()
        try:
            # 创建公司表（用于记录有哪些公司）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS companies (
                    company_name TEXT PRIMARY KEY,
                    priority TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # 如果表已存在但没有新字段，添加新字段（数据库迁移）
            try:
                conn.execute("ALTER TABLE companies ADD COLUMN priority TEXT")
            except sqlite3.OperationalError:
                pass  # 字段已存在
            
            # 创建公司平台表（每个平台一条记录）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_platforms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    game_name TEXT,
                    platform_type TEXT NOT NULL,
                    username TEXT,
                    url TEXT,
                    user_id TEXT,
                    page_id TEXT,
                    channel_id TEXT,
                    handle TEXT,
                    sec_uid TEXT,
                    enabled INTEGER DEFAULT 1,
                    priority TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(company_name, game_name, platform_type, url)
                )
            """)
            
            # 创建索引以提高查询性能
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_company_platforms_company 
                ON company_platforms(company_name)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_company_platforms_game 
                ON company_platforms(company_name, game_name)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_company_platforms_type 
                ON company_platforms(platform_type)
            """)
            
            # 创建索引表（用于快速查找公司表）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS company_tables_index (
                    company_name TEXT PRIMARY KEY,
                    table_name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                )
            """)
            
            # 创建周报表（用于存储生成的周报）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weekly_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company_name TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    report_content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(company_name, start_date, end_date)
                )
            """)
            
            # 创建索引以提高查询性能
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weekly_reports_company 
                ON weekly_reports(company_name)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weekly_reports_dates 
                ON weekly_reports(start_date, end_date)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_weekly_reports_created 
                ON weekly_reports(created_at)
            """)
            
            conn.commit()
        finally:
            conn.close()
    
    def _get_table_name(self, company: str) -> str:
        """
        获取公司对应的表名（清理特殊字符，确保表名合法）
        
        Args:
            company: 公司名称
        
        Returns:
            表名（格式：company_raw_data_公司名）
        """
        # 清理特殊字符，只保留字母、数字、下划线
        safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in company)
        safe_name = safe_name.replace(' ', '_').replace('-', '_').lower()
        return f"company_raw_data_{safe_name}"
    
    def _ensure_company_table(self, company: str) -> str:
        """
        确保公司表存在，如果不存在则创建
        
        Args:
            company: 公司名称
        
        Returns:
            表名
        """
        table_name = self._get_table_name(company)
        conn = self._get_connection()
        try:
            # 检查表是否存在
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                # 创建表
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        fetch_date TEXT NOT NULL,
                        platform_type TEXT NOT NULL,
                        game TEXT,
                        url TEXT,
                        username TEXT,
                        page_id TEXT,
                        channel_id TEXT,
                        handle TEXT,
                        posts_count INTEGER DEFAULT 0,
                        posts_json TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE(fetch_date, platform_type, game, url)
                    )
                """)
                
                # 创建索引以提高查询性能
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_date 
                    ON {table_name}(fetch_date)
                """)
                
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{table_name}_platform 
                    ON {table_name}(platform_type, game)
                """)
                
                conn.commit()
                
                # 记录到索引表
                conn.execute("""
                    INSERT OR IGNORE INTO company_tables_index (company_name, table_name, created_at)
                    VALUES (?, ?, ?)
                """, (company, table_name, datetime.utcnow().isoformat() + "Z"))
                
                # 记录到公司表（如果不存在则创建，如果存在则更新 updated_at）
                conn.execute("""
                    INSERT OR IGNORE INTO companies (company_name, created_at, updated_at)
                    VALUES (?, ?, ?)
                """, (company, datetime.utcnow().isoformat() + "Z", datetime.utcnow().isoformat() + "Z"))
                
                conn.execute("""
                    UPDATE companies SET updated_at = ? WHERE company_name = ?
                """, (datetime.utcnow().isoformat() + "Z", company))
                
                conn.commit()
                print(f"  ✓ 已创建公司表: {table_name}")
        
        finally:
            conn.close()
        
        return table_name
    
    def save_raw_data(
        self, 
        company: str, 
        platforms_data: List[Dict[str, Any]], 
        fetch_date: Optional[date] = None
    ) -> bool:
        """
        保存原始爬取数据到数据库
        
        Args:
            company: 公司名称
            platforms_data: 各平台的数据列表，每个元素包含：
                - platform_type: 平台类型（twitter, tiktok, youtube, facebook等）
                - game: 子产品名称（可选，兼容旧字段，新结构下通常为 None）
                - url: 账号URL
                - posts: 帖子列表
                - posts_count: 帖子数量
                - fetched_at: 抓取时间
            fetch_date: 抓取日期，默认为今天
        
        Returns:
            是否保存成功
        """
        if fetch_date is None:
            fetch_date = date.today()
        
        date_str = fetch_date.strftime("%Y-%m-%d")
        table_name = self._ensure_company_table(company)
        
        conn = self._get_connection()
        try:
            for platform_data in platforms_data:
                platform_type = platform_data.get("platform_type", "unknown")
                game = platform_data.get("game")
                url = platform_data.get("url", "")
                username = platform_data.get("username")
                page_id = platform_data.get("page_id")
                channel_id = platform_data.get("channel_id")
                handle = platform_data.get("handle")
                posts = platform_data.get("posts", [])
                posts_count = platform_data.get("posts_count", 0)
                fetched_at = platform_data.get("fetched_at") or datetime.utcnow().isoformat() + "Z"
                
                # 将 posts 转换为 JSON 字符串
                posts_json = json.dumps(posts, ensure_ascii=False)
                
                # 插入或更新数据（使用 INSERT OR REPLACE）
                conn.execute(f"""
                    INSERT OR REPLACE INTO {table_name} (
                        fetch_date, platform_type, game, url, username, page_id, 
                        channel_id, handle, posts_count, posts_json, fetched_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date_str,
                    platform_type,
                    game,
                    url,
                    username,
                    page_id,
                    channel_id,
                    handle,
                    posts_count,
                    posts_json,
                    fetched_at,
                    datetime.utcnow().isoformat() + "Z"
                ))
            
            conn.commit()
            print(f"  ✓ 已保存原始数据到数据库表: {table_name} (公司: {company}, 日期: {date_str})")
            return True
        
        except Exception as exc:
            conn.rollback()
            print(f"  ❌ 保存原始数据失败: {exc}")
            import traceback
            print(f"  [调试] 错误详情: {traceback.format_exc()}")
            return False
        
        finally:
            conn.close()
    
    def load_raw_data(
        self, 
        company: str, 
        fetch_date: Optional[date] = None
    ) -> Optional[Dict[str, Any]]:
        """
        加载指定公司的原始爬取数据
        
        Args:
            company: 公司名称
            fetch_date: 日期，默认为今天
        
        Returns:
            数据字典，格式与 JSON 文件格式兼容：
            {
                "company": company,
                "date": date_str,
                "fetched_at": ...,
                "platforms": {
                    "platform_key": {
                        "platform_type": ...,
                        "game": ...,
                        "posts": [...],
                        ...
                    }
                }
            }
        """
        if fetch_date is None:
            fetch_date = date.today()
        
        date_str = fetch_date.strftime("%Y-%m-%d")
        table_name = self._get_table_name(company)
        
        conn = self._get_connection()
        try:
            # 检查表是否存在
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return None
            
            # 查询数据
            cursor = conn.execute(f"""
                SELECT 
                    fetch_date, platform_type, game, url, username, page_id,
                    channel_id, handle, posts_count, posts_json, fetched_at
                FROM {table_name}
                WHERE fetch_date = ?
                ORDER BY platform_type, game
            """, (date_str,))
            
            rows = cursor.fetchall()
            if not rows:
                return None
            
            # 构建返回数据
            platforms_dict = {}
            latest_fetched_at = None
            
            for row in rows:
                platform_type = row["platform_type"]
                game = row["game"]
                
                # 构建平台键
                key = platform_type
                if game:
                    key = f"{platform_type}_{game}"
                
                # 解析 posts JSON
                posts = []
                try:
                    posts = json.loads(row["posts_json"])
                except Exception:
                    posts = []
                
                platforms_dict[key] = {
                    "platform_type": platform_type,
                    "game": game,
                    "url": row["url"],
                    "username": row["username"],
                    "page_id": row["page_id"],
                    "channel_id": row["channel_id"],
                    "handle": row["handle"],
                    "posts": posts,
                    "posts_count": row["posts_count"],
                    "fetched_at": row["fetched_at"],
                }
                
                # 记录最新的 fetched_at
                if not latest_fetched_at or row["fetched_at"] > latest_fetched_at:
                    latest_fetched_at = row["fetched_at"]
            
            return {
                "company": company,
                "date": date_str,
                "fetched_at": latest_fetched_at or datetime.utcnow().isoformat() + "Z",
                "platforms": platforms_dict
            }
        
        except Exception as exc:
            print(f"  ⚠️ 加载原始数据失败: {exc}")
            import traceback
            print(f"  [调试] 错误详情: {traceback.format_exc()}")
            return None
        
        finally:
            conn.close()
    
    def load_raw_data_by_date(self, fetch_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
        """
        按日期加载所有公司的原始爬取数据（兼容旧接口）
        
        Args:
            fetch_date: 日期，默认为今天
        
        Returns:
            数据字典，格式：
            {
                "date": date_str,
                "fetched_at": ...,
                "companies": {
                    company_name: {
                        "company": ...,
                        "platforms": {...}
                    }
                }
            }
        """
        if fetch_date is None:
            fetch_date = date.today()
        
        date_str = fetch_date.strftime("%Y-%m-%d")
        
        # 获取所有公司列表
        companies = self.get_all_companies()
        if not companies:
            return None
        
        companies_dict = {}
        latest_fetched_at = None
        
        for company in companies:
            company_data = self.load_raw_data(company, fetch_date)
            if company_data:
                companies_dict[company] = company_data
                fetched_at = company_data.get("fetched_at")
                if fetched_at and (not latest_fetched_at or fetched_at > latest_fetched_at):
                    latest_fetched_at = fetched_at
        
        if not companies_dict:
            return None
        
        return {
            "date": date_str,
            "fetched_at": latest_fetched_at or datetime.utcnow().isoformat() + "Z",
            "companies": companies_dict
        }
    
    def get_all_companies(self) -> List[str]:
        """
        获取所有有数据的公司列表
        
        Returns:
            公司名称列表
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT company_name FROM companies
                ORDER BY company_name
            """)
            return [row["company_name"] for row in cursor.fetchall()]
        finally:
            conn.close()
    
    def get_companies_for_date(self, target_date: Optional[date] = None) -> List[str]:
        """
        获取指定日期有数据的公司列表
        
        Args:
            target_date: 日期，默认为今天
        
        Returns:
            公司名称列表
        """
        if target_date is None:
            target_date = date.today()
        
        date_str = target_date.strftime("%Y-%m-%d")
        companies = []
        
        for company in self.get_all_companies():
            table_name = self._get_table_name(company)
            conn = self._get_connection()
            try:
                cursor = conn.execute(f"""
                    SELECT COUNT(*) as count FROM {table_name}
                    WHERE fetch_date = ?
                """, (date_str,))
                
                row = cursor.fetchone()
                if row and row["count"] > 0:
                    companies.append(company)
            except Exception:
                # 表不存在或查询失败，跳过
                pass
            finally:
                conn.close()
        
        return sorted(companies)
    
    def get_all_dates_for_company(self, company: str) -> List[str]:
        """
        获取指定公司有数据的日期列表
        
        Args:
            company: 公司名称
        
        Returns:
            日期字符串列表（YYYY-MM-DD），按日期倒序
        """
        table_name = self._get_table_name(company)
        conn = self._get_connection()
        try:
            # 检查表是否存在
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return []
            
            cursor = conn.execute(f"""
                SELECT DISTINCT fetch_date FROM {table_name}
                ORDER BY fetch_date DESC
            """)
            
            return [row["fetch_date"] for row in cursor.fetchall()]
        
        except Exception:
            return []
        
        finally:
            conn.close()
    
    def get_platform_video_ids(
        self,
        company: str,
        game: Optional[str],
        platform_type: str,
        url: str,
        fetch_date: Optional[date] = None
    ) -> set[str]:
        """
        获取指定平台在指定日期的所有视频ID（用于去重）
        
        Args:
            company: 公司名称
            game: 子产品名称（可选，兼容旧字段）
            platform_type: 平台类型
            url: 平台URL
            fetch_date: 日期，默认为今天
        
        Returns:
            video_id 集合
        """
        if fetch_date is None:
            fetch_date = date.today()
        
        date_str = fetch_date.strftime("%Y-%m-%d")
        table_name = self._get_table_name(company)
        
        conn = self._get_connection()
        video_ids = set()
        
        try:
            # 检查表是否存在
            cursor = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,))
            
            if not cursor.fetchone():
                return video_ids
            
            # 查询匹配的平台数据
            query = f"""
                SELECT posts_json FROM {table_name}
                WHERE fetch_date = ? AND platform_type = ? AND url = ?
            """
            params = [date_str, platform_type, url]
            
            if game:
                query += " AND game = ?"
                params.append(game)
            else:
                query += " AND game IS NULL"
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            # 从 posts JSON 中提取 video_id
            for row in rows:
                try:
                    posts = json.loads(row["posts_json"])
                    for post in posts:
                        # 尝试多种可能的字段名
                        video_id = (
                            post.get("video_id") or 
                            post.get("videoId") or 
                            post.get("id") or
                            ""
                        )
                        if video_id:
                            video_ids.add(video_id)
                        
                        # 也可以从 post_url 中提取（用于 YouTube Shorts）
                        post_url = post.get("post_url", "")
                        if "/shorts/" in post_url:
                            match = re.search(r'/shorts/([A-Za-z0-9_-]+)', post_url)
                            if match:
                                video_ids.add(match.group(1))
                        elif "/watch?v=" in post_url:
                            # 普通 YouTube 视频
                            match = re.search(r'/watch\?v=([A-Za-z0-9_-]+)', post_url)
                            if match:
                                video_ids.add(match.group(1))
                except Exception:
                    continue
        
        finally:
            conn.close()
        
        return video_ids
    
    def save_company_social_media_config(
        self,
        company: str,
        priority: Optional[str],
        social_media_config: Dict[str, Any]
    ) -> bool:
        """
        保存公司的社媒配置信息（每个平台一条记录）
        
        Args:
            company: 公司名称
            priority: 优先级（high, medium, low）
            social_media_config: 社媒配置字典，包含 platforms 和 games
        
        Returns:
            是否保存成功
        """
        conn = self._get_connection()
        try:
            now = datetime.utcnow().isoformat() + "Z"
            
            # 更新或插入公司记录
            conn.execute("""
                INSERT OR IGNORE INTO companies (company_name, priority, created_at, updated_at)
                VALUES (?, ?, ?, ?)
            """, (company, priority, now, now))
            
            conn.execute("""
                UPDATE companies SET priority = ?, updated_at = ? WHERE company_name = ?
            """, (priority, now, company))
            
            # 保存公司级平台
            platforms = social_media_config.get("platforms", [])
            for platform in platforms:
                self._save_platform_record(
                    conn, company, None, platform, priority, now
                )
            
            # 保存子产品级平台（兼容旧结构的 games 层级）
            games = social_media_config.get("games", [])
            for game in games:
                game_name = game.get("name", "").strip()
                if not game_name:
                    continue
                
                game_platforms = game.get("platforms", [])
                for platform in game_platforms:
                    self._save_platform_record(
                        conn, company, game_name, platform, priority, now
                    )
            
            conn.commit()
            print(f"  ✓ 已保存产品社媒配置: {company} ({len(platforms)} 个产品平台, {sum(len(g.get('platforms', [])) for g in games)} 个子产品平台)")
            return True
        
        except Exception as exc:
            conn.rollback()
            print(f"  ❌ 保存公司社媒配置失败: {exc}")
            import traceback
            print(f"  [调试] 错误详情: {traceback.format_exc()}")
            return False
        
        finally:
            conn.close()
    
    def _save_platform_record(
        self,
        conn: sqlite3.Connection,
        company: str,
        game_name: Optional[str],
        platform: Dict[str, Any],
        company_priority: Optional[str],
        now: str
    ):
        """
        保存单个平台记录（支持去重和覆盖）
        
        去重规则：
        - 产品名 + 子产品名（NULL 视为一致）+ 平台类型 一致时，覆盖原有配置
        - URL 不作为去重条件（因为同一个平台可能有多个 URL）
        
        Args:
            conn: 数据库连接
            company: 公司名称
            game_name: 子产品名称（None 表示产品级平台，兼容旧字段）
            platform: 平台配置字典
            company_priority: 公司优先级
            now: 当前时间戳
        """
        platform_type = platform.get("type", "").strip()
        if not platform_type:
            return
        
        enabled = 1 if platform.get("enabled", True) else 0
        url = platform.get("url", "")
        
        # 检查记录是否已存在（基于：产品名 + 子产品名 + 平台类型）
        # 注意：game_name 为 NULL 时，使用 IS NULL 进行匹配
        if game_name:
            cursor = conn.execute("""
                SELECT id, created_at FROM company_platforms
                WHERE company_name = ? AND game_name = ? AND platform_type = ?
            """, (company, game_name, platform_type))
        else:
            cursor = conn.execute("""
                SELECT id, created_at FROM company_platforms
                WHERE company_name = ? AND game_name IS NULL AND platform_type = ?
            """, (company, platform_type))
        
        existing_row = cursor.fetchone()
        
        if existing_row:
            # 记录已存在，更新（保留 created_at）
            existing_created_at = existing_row["created_at"]
            existing_id = existing_row["id"]
            
            conn.execute("""
                UPDATE company_platforms SET
                    username = ?,
                    url = ?,
                    user_id = ?,
                    page_id = ?,
                    channel_id = ?,
                    handle = ?,
                    sec_uid = ?,
                    enabled = ?,
                    priority = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                platform.get("username"),
                url,
                platform.get("user_id"),
                platform.get("page_id"),
                platform.get("channel_id"),
                platform.get("handle"),
                platform.get("sec_uid"),
                enabled,
                company_priority,
                now,
                existing_id
            ))
        else:
            # 记录不存在，插入新记录
            conn.execute("""
                INSERT INTO company_platforms (
                    company_name, game_name, platform_type, username, url,
                    user_id, page_id, channel_id, handle, sec_uid, enabled, priority,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                company,
                game_name,
                platform_type,
                platform.get("username"),
                url,
                platform.get("user_id"),
                platform.get("page_id"),
                platform.get("channel_id"),
                platform.get("handle"),
                platform.get("sec_uid"),
                enabled,
                company_priority,
                now,
                now
            ))
    
    def load_company_social_media_config(self, company: str) -> Optional[Dict[str, Any]]:
        """
        加载公司的社媒配置信息（从平台表中读取）
        
        Args:
            company: 公司名称
        
        Returns:
            配置字典，包含 priority, platforms, games，如果不存在则返回 None
        """
        conn = self._get_connection()
        try:
            # 获取公司信息
            cursor = conn.execute("""
                SELECT priority FROM companies WHERE company_name = ?
            """, (company,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            priority = row["priority"]
            
            # 获取所有平台记录
            cursor = conn.execute("""
                SELECT game_name, platform_type, username, url, user_id, page_id,
                       channel_id, handle, sec_uid, enabled
                FROM company_platforms
                WHERE company_name = ?
                ORDER BY game_name NULLS FIRST, platform_type
            """, (company,))
            
            rows = cursor.fetchall()
            if not rows:
                return {
                    "priority": priority,
                    "platforms": [],
                    "games": []
                }
            
            # 分离产品级平台和子产品级平台
            company_platforms = []
            games_dict = {}
            
            for row in rows:
                game_name = row["game_name"]
                platform = {
                    "type": row["platform_type"],
                    "enabled": bool(row["enabled"])
                }
                
                # 添加可选字段
                if row["username"]:
                    platform["username"] = row["username"]
                if row["url"]:
                    platform["url"] = row["url"]
                if row["user_id"]:
                    platform["user_id"] = row["user_id"]
                if row["page_id"]:
                    platform["page_id"] = row["page_id"]
                if row["channel_id"]:
                    platform["channel_id"] = row["channel_id"]
                if row["handle"]:
                    platform["handle"] = row["handle"]
                if row["sec_uid"]:
                    platform["sec_uid"] = row["sec_uid"]
                
                if game_name:
                    # 子产品级平台（兼容旧数据）
                    if game_name not in games_dict:
                        games_dict[game_name] = {"name": game_name, "platforms": []}
                    games_dict[game_name]["platforms"].append(platform)
                else:
                    # 公司级平台
                    company_platforms.append(platform)
            
            return {
                "priority": priority,
                "platforms": company_platforms,
                "games": list(games_dict.values())
            }
        
        except Exception as exc:
            print(f"  ⚠️ 加载公司社媒配置失败: {exc}")
            import traceback
            print(f"  [调试] 错误详情: {traceback.format_exc()}")
            return None
        
        finally:
            conn.close()
    
    def load_all_companies_config(self) -> Dict[str, Dict[str, Any]]:
        """
        加载所有公司的社媒配置
        
        Returns:
            字典，key 为公司名，value 为配置信息
        """
        companies = self.get_all_companies()
        result = {}
        
        for company in companies:
            config = self.load_company_social_media_config(company)
            if config:
                result[company] = config
        
        return result
    
    def get_company_platforms(
        self,
        company: str,
        game_name: Optional[str] = None,
        platform_type: Optional[str] = None,
        enabled_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        获取公司的平台列表
        
        Args:
            company: 公司名称
            game_name: 子产品名称（None 表示只获取产品级平台）
            platform_type: 平台类型（None 表示所有类型）
            enabled_only: 是否只返回启用的平台
        
        Returns:
            平台列表
        """
        conn = self._get_connection()
        try:
            query = """
                SELECT game_name, platform_type, username, url, user_id, page_id,
                       channel_id, handle, sec_uid, enabled, priority
                FROM company_platforms
                WHERE company_name = ?
            """
            params = [company]
            
            if game_name is not None:
                query += " AND game_name = ?"
                params.append(game_name)
            else:
                query += " AND game_name IS NULL"
            
            if platform_type:
                query += " AND platform_type = ?"
                params.append(platform_type)
            
            if enabled_only:
                query += " AND enabled = 1"
            
            query += " ORDER BY platform_type"
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            platforms = []
            for row in rows:
                platform = {
                    "type": row["platform_type"],
                    "enabled": bool(row["enabled"])
                }
                
                if row["game_name"]:
                    platform["game"] = row["game_name"]
                if row["username"]:
                    platform["username"] = row["username"]
                if row["url"]:
                    platform["url"] = row["url"]
                if row["user_id"]:
                    platform["user_id"] = row["user_id"]
                if row["page_id"]:
                    platform["page_id"] = row["page_id"]
                if row["channel_id"]:
                    platform["channel_id"] = row["channel_id"]
                if row["handle"]:
                    platform["handle"] = row["handle"]
                if row["sec_uid"]:
                    platform["sec_uid"] = row["sec_uid"]
                if row["priority"]:
                    platform["priority"] = row["priority"]
                
                platforms.append(platform)
            
            return platforms
        
        except Exception as exc:
            print(f"  ⚠️ 获取公司平台列表失败: {exc}")
            return []
        
        finally:
            conn.close()
    
    def save_weekly_report(
        self,
        company: str,
        start_date: date,
        end_date: date,
        report_content: Dict[str, Any]
    ) -> bool:
        """
        保存周报到数据库
        
        Args:
            company: 公司名称
            start_date: 开始日期
            end_date: 结束日期
            report_content: 周报内容（字典格式，会被转换为JSON字符串）
        
        Returns:
            是否保存成功
        """
        conn = self._get_connection()
        try:
            # 将报告内容转换为JSON字符串
            report_json = json.dumps(report_content, ensure_ascii=False, indent=2)
            
            # 转换为日期字符串
            start_date_str = start_date.isoformat()
            end_date_str = end_date.isoformat()
            created_at = datetime.now().isoformat()
            
            # 使用 INSERT OR REPLACE 实现更新或插入
            conn.execute("""
                INSERT OR REPLACE INTO weekly_reports 
                (company_name, start_date, end_date, report_content, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (company, start_date_str, end_date_str, report_json, created_at))
            
            conn.commit()
            return True
        
        except Exception as exc:
            print(f"  ⚠️ 保存周报到数据库失败: {exc}")
            import traceback
            print(f"  [调试] 错误详情: {traceback.format_exc()}")
            conn.rollback()
            return False
        
        finally:
            conn.close()
    
    def get_weekly_report(
        self,
        company: str,
        start_date: date,
        end_date: date
    ) -> Optional[Dict[str, Any]]:
        """
        从数据库获取周报
        
        Args:
            company: 公司名称
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            周报内容（字典格式），如果不存在则返回 None
        """
        conn = self._get_connection()
        try:
            start_date_str = start_date.isoformat()
            end_date_str = end_date.isoformat()
            
            cursor = conn.execute("""
                SELECT report_content, created_at
                FROM weekly_reports
                WHERE company_name = ? AND start_date = ? AND end_date = ?
            """, (company, start_date_str, end_date_str))
            
            row = cursor.fetchone()
            if row:
                report_content = json.loads(row["report_content"])
                return {
                    "report": report_content,
                    "created_at": row["created_at"]
                }
            return None
        
        except Exception as exc:
            print(f"  ⚠️ 获取周报失败: {exc}")
            return None
        
        finally:
            conn.close()
    
    def get_weekly_reports_by_company(
        self,
        company: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        获取指定公司的所有周报（按创建时间倒序）
        
        Args:
            company: 公司名称
            limit: 返回数量限制（可选）
        
        Returns:
            周报列表
        """
        conn = self._get_connection()
        try:
            query = """
                SELECT company_name, start_date, end_date, report_content, created_at
                FROM weekly_reports
                WHERE company_name = ?
                ORDER BY created_at DESC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor = conn.execute(query, (company,))
            
            reports = []
            for row in cursor.fetchall():
                reports.append({
                    "company": row["company_name"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "report": json.loads(row["report_content"]),
                    "created_at": row["created_at"]
                })
            
            return reports
        
        except Exception as exc:
            print(f"  ⚠️ 获取公司周报列表失败: {exc}")
            return []
        
        finally:
            conn.close()


if __name__ == "__main__":
    # 简单测试
    db = CompetitorDatabaseDB()
    
    # 测试保存原始数据
    test_data = [
        {
            "platform_type": "twitter",
            "game": None,
            "url": "https://x.com/test",
            "posts": [{"text": "test", "post_url": "https://x.com/test/1", "video_id": "test123"}],
            "posts_count": 1,
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }
    ]
    db.save_raw_data("Test Company", test_data)
    
    # 测试加载
    loaded = db.load_raw_data("Test Company")
    print(f"加载结果: {loaded is not None}")
    if loaded:
        print(f"平台数量: {len(loaded.get('platforms', {}))}")
