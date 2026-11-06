"""调用 embedding 模型生成向量，缓存文档向量并按余弦相似度检索。"""

from math import isfinite, sqrt
import hashlib
import json
import os
from pathlib import Path
import tempfile

from openai import OpenAI

from rag import Chunk


def embed(client: OpenAI, texts: list[str], model: str) -> list[list[float]]:
    """分批向量化。顺序与 texts 一致；每批最多 10 条。"""
    vectors = []
    for start in range(0, len(texts), 10):
        batch = texts[start:start + 10]
        response = client.embeddings.create(model=model, input=batch, encoding_format="float")
        items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(len(batch))):
            raise ValueError("Embedding 返回的条数或顺序异常。")
        vectors.extend(item.embedding for item in items)
    return vectors


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """比较向量方向；越接近 1 通常表示语义越接近，不是正确率。"""
    if not left or len(left) != len(right):
        raise ValueError("Embedding 向量为空或维度不一致。")
    if not all(isfinite(value) for value in left + right):
        raise ValueError("Embedding 向量包含无效数字。")
    norm = sqrt(sum(value * value for value in left)) * sqrt(sum(value * value for value in right))
    if norm == 0:
        raise ValueError("Embedding 返回了零向量。")
    return sum(a * b for a, b in zip(left, right)) / norm


def retrieve_vectors(
    client: OpenAI, question: str, chunks: list[Chunk], model: str, top_k: int = 3,
    cache_path: Path | None = None,
) -> list[tuple[float, Chunk]]:
    """问题和文档使用同一个模型，才能在相同向量空间中比较。"""
    if not chunks:
        return []
    # 缓存键包含服务地址、模型和片段正文，避免文档修改或切换模型后复用旧向量。
    cache = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(cache, dict):
                cache = {}
        except (OSError, ValueError):
            cache = {}
    keys = [hashlib.sha256(f"{client.base_url}\n{model}\n{chunk.text}".encode()).hexdigest()
            for chunk in chunks]
    def valid(vector):
        return (isinstance(vector, list) and bool(vector)
                and all(type(v) in (int, float) and isfinite(v) for v in vector)
                and any(v != 0 for v in vector))
    missing = {key: chunk.text for key, chunk in zip(keys, chunks) if not valid(cache.get(key))}
    if missing:
        new_vectors = embed(client, list(missing.values()), model)
        if not all(valid(vector) for vector in new_vectors):
            raise ValueError("Embedding 返回无效向量。")
        cache.update(zip(missing, new_vectors))
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=cache_path.parent,
                                                 delete=False) as handle:
                    temporary = Path(handle.name)
                    json.dump(cache, handle)
                os.replace(temporary, cache_path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
    question_vector = embed(client, [question], model)[0]
    scored = [
        (cosine_similarity(question_vector, vector), chunk)
        for key, chunk in zip(keys, chunks)
        for vector in [cache[key]]
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:top_k]
