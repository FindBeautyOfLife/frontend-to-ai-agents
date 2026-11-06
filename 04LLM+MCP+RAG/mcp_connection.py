"""启动独立工具进程，完成 MCP 握手并管理会话生命周期。"""

from contextlib import asynccontextmanager
from datetime import timedelta
import sys
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import ROOT


@asynccontextmanager
async def connect_tools(env: dict | None = None):
    # 显式传递本项目配置；不把无关应用的环境变量交给工具服务。
    names = ("DASHSCOPE_API_KEY", "BAILIAN_BASE_URL", "BAILIAN_MODEL",
             "BAILIAN_EMBEDDING_MODEL", "KNOWLEDGE_DIR", "OUTPUT_DIR", "CACHE_DIR")
    server_env = {name: os.environ[name] for name in names if name in os.environ}
    server_env["PYTHONIOENCODING"] = "utf-8"
    server_env.update(env or {})
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "tool_server.py")],
                                   env=server_env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
            await session.initialize()
            yield session
