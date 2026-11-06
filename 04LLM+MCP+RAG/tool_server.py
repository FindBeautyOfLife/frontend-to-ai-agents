"""MCP stdio 工具服务；标准输出专用于协议消息，避免混入普通日志。"""

import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import KNOWLEDGE_DIR, OUTPUT_DIR
from knowledge_service import search_knowledge

mcp = FastMCP("local-knowledge-assistant", log_level="WARNING")


def safe_document(filename: str) -> Path:
    path = (KNOWLEDGE_DIR / filename).resolve()
    if not path.is_relative_to(KNOWLEDGE_DIR) or path.suffix.lower() not in {".md", ".txt"}:
        raise ValueError("只能访问 knowledge 内的 .md/.txt 文件。")
    if not path.is_file():
        raise ValueError("文档不存在。")
    return path


@mcp.tool()
def list_documents() -> list[str]:
    """列出 knowledge 文件夹内可用的 Markdown 和 TXT 文档。"""
    return [p.relative_to(KNOWLEDGE_DIR).as_posix() for p in sorted(KNOWLEDGE_DIR.rglob("*"))
            if p.is_file() and p.suffix.lower() in {".md", ".txt"}
            and p.resolve().is_relative_to(KNOWLEDGE_DIR)]


@mcp.tool()
def read_document(filename: str) -> str:
    """读取 knowledge 内的文档全文，filename 使用 list_documents 返回的相对路径。"""
    path = safe_document(filename)
    if path.stat().st_size > 100_000:
        raise ValueError("文档过大，请使用 search_documents 分段检索。")
    return path.read_text(encoding="utf-8-sig")


@mcp.tool()
def search_documents(query: str, mode: str = "vector", top_k: int = 3) -> dict:
    """检索知识库。vector 为语义检索，keyword 为关键词检索，返回带来源编号的片段。"""
    try:
        return search_knowledge(query, mode, top_k)
    except Exception:
        # MCP 工具错误会发给模型，不把服务响应和密钥放进错误文本。
        raise ValueError("检索失败，请检查文档编码、网络、embedding 配置和模型权限。") from None


@mcp.tool()
def save_note(filename: str, content: str) -> str:
    """仅在用户明确要求保存时调用。将清单或笔记保存到 outputs，不能覆盖已有文件。

    filename 只接受简单 .md/.txt 文件名，不接受路径。content 为需要保存的完整正文。
    """
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff][\w\-\u4e00-\u9fff.]{0,79}\.(md|txt)", filename):
        raise ValueError("请使用不含路径的 .md/.txt 文件名。")
    if filename.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)}, *{f"LPT{i}" for i in range(1, 10)}}:
        raise ValueError("不能使用系统保留文件名。")
    if not content.strip() or len(content) > 50_000:
        raise ValueError("正文不能为空且不能超过 50000 字。")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / filename
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError:
        raise ValueError("文件已存在，请换一个文件名。") from None
    return f"已保存：outputs/{filename}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
