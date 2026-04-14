from pathlib import Path

from dotenv import load_dotenv


# 默认从项目根目录的 .env 加载；如果当前工作目录不同，也会向上搜索
load_dotenv(dotenv_path=Path(".") / ".env", override=False)

