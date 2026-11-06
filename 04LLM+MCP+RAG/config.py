"""统一配置；读取 .env，但不在日志中展示密钥。"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", str(ROOT / "knowledge"))).resolve()
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", str(ROOT / "outputs"))).resolve()
CACHE_DIR = Path(os.getenv("CACHE_DIR", str(ROOT / ".cache"))).resolve()


def model_name() -> str:
    value = os.getenv("BAILIAN_MODEL", "").strip()
    if not value:
        raise ValueError("请在 .env 中设置 BAILIAN_MODEL。")
    return value


def embedding_model() -> str:
    value = os.getenv("BAILIAN_EMBEDDING_MODEL", "text-embedding-v4").strip()
    if not value:
        raise ValueError("BAILIAN_EMBEDDING_MODEL 不能为空。")
    return value


def create_client() -> OpenAI:
    missing = [name for name in ("DASHSCOPE_API_KEY", "BAILIAN_BASE_URL")
               if not os.getenv(name, "").strip()]
    if missing:
        raise ValueError("请在 .env 中设置：" + ", ".join(missing))
    return OpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"].strip(),
        base_url=os.environ["BAILIAN_BASE_URL"].strip(),
        timeout=60.0,
        max_retries=0,
    )
