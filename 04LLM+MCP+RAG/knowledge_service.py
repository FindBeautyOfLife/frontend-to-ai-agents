"""检索业务层：CLI 和 MCP 服务共用同一套 RAG。"""

from pathlib import Path

from config import CACHE_DIR, KNOWLEDGE_DIR, create_client, embedding_model
from rag import format_context, load_chunks, retrieve
from vector_search import retrieve_vectors


def search_knowledge(query: str, mode: str = "vector", top_k: int = 3,
                     directory: Path = KNOWLEDGE_DIR) -> dict:
    if not query.strip():
        raise ValueError("问题不能为空。")
    if mode not in {"keyword", "vector"} or not 1 <= top_k <= 10:
        raise ValueError("mode 应为 keyword/vector，top_k 应在 1～10 之间。")
    chunks = load_chunks(directory)
    if not chunks:
        return {"context": "", "sources": [], "message": "知识库为空，请添加 UTF-8 的 .md 或 .txt 文档。"}
    if mode == "keyword":
        matches = retrieve(query, chunks, top_k)
        scores = [None] * len(matches)
    else:
        with create_client() as client:
            ranked = retrieve_vectors(client, query, chunks, embedding_model(), top_k,
                                      cache_path=CACHE_DIR / "embeddings.json")
        matches = [chunk for score, chunk in ranked]
        scores = [round(score, 4) for score, chunk in ranked]
    return {
        "context": format_context(matches),
        "sources": [{"id": i, "source": chunk.source, "score": score}
                    for i, (chunk, score) in enumerate(zip(matches, scores), 1)],
        "message": "相似度不是正确率，需判断资料是否足以回答。" if matches else "没有匹配片段。",
    }
