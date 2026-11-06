"""文档读取、段落切分与关键词检索；此模块不调用模型服务。"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Chunk:
    source: str
    text: str


def load_chunks(directory: Path) -> list[Chunk]:
    """读取 UTF-8 的 .md/.txt，以空行分段；长段落按 500 字切分，重叠 80 字。"""
    directory = directory.resolve()
    chunks = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        if not path.resolve().is_relative_to(directory):
            continue
        content = path.read_text(encoding="utf-8-sig")
        number = 0
        for paragraph in re.split(r"\n\s*\n", content):
            paragraph = paragraph.strip()
            # 每次前进 420 字、读取 500 字，使相邻长片段保留 80 字上下文。
            for start in range(0, len(paragraph), 420):
                number += 1
                chunks.append(Chunk(
                    source=f"{path.relative_to(directory).as_posix()}#片段{number}",
                    text=paragraph[start:start + 500],
                ))
                if start + 500 >= len(paragraph):
                    break
    return chunks


def terms(text: str) -> set[str]:
    """英文按单词匹配，中文按相邻两个汉字匹配，例如“知识库”→“知识”“识库”。"""
    result = set(re.findall(r"[a-z0-9_]+", text.lower()))
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.update(run[index:index + 2] for index in range(len(run) - 1))
    return result


def retrieve(question: str, chunks: list[Chunk], top_k: int = 3) -> list[Chunk]:
    """按问题与片段共享的词语数量排序，只返回有匹配的前 top_k 个片段。"""
    question_terms = terms(question)
    scored = [(len(question_terms & terms(chunk.text)), chunk) for chunk in chunks]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for score, chunk in scored[:top_k] if score > 0]


def format_context(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f"[{index}] 来源：{chunk.source}\n{chunk.text}"
        for index, chunk in enumerate(chunks, start=1)
    )
