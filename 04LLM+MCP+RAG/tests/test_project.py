"""离线测试：检索、缓存、文件边界以及真实 MCP stdio 通信。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from openai.types.chat import ChatCompletionMessage

from agent import run_turn, trim_history
from mcp_connection import connect_tools
from rag import Chunk, load_chunks, retrieve
from vector_search import cosine_similarity, retrieve_vectors
import tool_server


class RetrievalTests(unittest.TestCase):
    def test_chunks_and_keyword(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "notes.md").write_text("支持 Markdown 文档\n\n" + "甲" * 1000, encoding="utf-8")
            (root / "ignore.csv").write_text("不要读取", encoding="utf-8")
            chunks = load_chunks(root)
            self.assertEqual([len(c.text) for c in chunks[1:]], [500, 500, 160])
            self.assertEqual(retrieve("Markdown", chunks)[0].source, "notes.md#片段1")
            self.assertEqual(retrieve("unmatchedxyz", chunks), [])

    def test_cosine_validation(self):
        self.assertEqual(cosine_similarity([1, 0], [1, 0]), 1)
        self.assertEqual(cosine_similarity([1, 0], [0, 1]), 0)
        for invalid in ([], [0, 0], [float("nan"), 0], [1]):
            with self.assertRaises(ValueError):
                cosine_similarity([1, 0], invalid)

    def test_cache_hits_and_invalidates(self):
        requests = []
        def create(**kwargs):
            requests.extend(kwargs["input"])
            return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[1., 0.])
                for i, text in reversed(list(enumerate(kwargs["input"])))])
        client = SimpleNamespace(base_url="https://example.test/v1",
                                 embeddings=SimpleNamespace(create=create))
        with TemporaryDirectory() as folder:
            cache = Path(folder) / "cache.json"
            chunks = [Chunk("a", "original")]
            retrieve_vectors(client, "question", chunks, "model-a", cache_path=cache)
            self.assertEqual(requests, ["original", "question"])
            requests.clear()
            retrieve_vectors(client, "question", chunks, "model-a", cache_path=cache)
            self.assertEqual(requests, ["question"])
            requests.clear()
            retrieve_vectors(client, "question", [Chunk("a", "changed")], "model-a", cache_path=cache)
            self.assertIn("changed", requests)
            requests.clear()
            retrieve_vectors(client, "question", chunks, "model-b", cache_path=cache)
            self.assertIn("original", requests)
            cache.write_text("broken", encoding="utf-8")
            retrieve_vectors(client, "question", chunks, "model-a", cache_path=cache)
            self.assertIsInstance(json.loads(cache.read_text()), dict)

    def test_history_keeps_whole_turns(self):
        messages = [{"role": "system", "content": "system"}]
        for i in range(10):
            messages.extend([{"role": "user", "content": str(i)},
                             {"role": "assistant", "tool_calls": [{"id": str(i)}]},
                             {"role": "tool", "tool_call_id": str(i), "content": "ok"},
                             {"role": "assistant", "content": "done"}])
        trim_history(messages, 2)
        self.assertEqual(messages[1]["content"], "8")
        self.assertEqual(len(messages), 9)


class FileToolTests(unittest.TestCase):
    def test_read_boundary_and_no_overwrite(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "ok.md").write_text("hello", encoding="utf-8")
            (root / "secret.txt").write_text("private", encoding="utf-8")
            with patch.object(tool_server, "KNOWLEDGE_DIR", knowledge), patch.object(tool_server, "OUTPUT_DIR", root / "outputs"):
                self.assertEqual(tool_server.read_document("ok.md"), "hello")
                for invalid in ("../secret.txt", str(root / "secret.txt"), ".env"):
                    with self.assertRaises(ValueError):
                        tool_server.read_document(invalid)
                tool_server.save_note("test.md", "original")
                for invalid in ("../outside.md", "CON.md", "sub/note.md"):
                    with self.assertRaises(ValueError):
                        tool_server.save_note(invalid, "bad")
                with self.assertRaises(ValueError):
                    tool_server.save_note("test.md", "overwritten")
                self.assertEqual((root / "outputs/test.md").read_text(), "original")


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_tools(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "demo.md").write_text("知识库支持 Markdown 文档。", encoding="utf-8")
            env = {"KNOWLEDGE_DIR": str(knowledge), "OUTPUT_DIR": str(root / "outputs"),
                   "CACHE_DIR": str(root / "cache")}
            async with connect_tools(env) as session:
                listed = (await session.list_tools()).tools
                self.assertEqual({t.name for t in listed}, {"list_documents", "read_document", "search_documents", "save_note"})
                for name, args in [("list_documents", {}), ("read_document", {"filename": "demo.md"}),
                                   ("search_documents", {"query": "Markdown", "mode": "keyword"}),
                                   ("save_note", {"filename": "demo.md", "content": "- test"})]:
                    result = await session.call_tool(name, args)
                    self.assertFalse(result.isError, name)
                self.assertEqual((root / "outputs/demo.md").read_text(), "- test")
                result = await session.call_tool("read_document", {"filename": "../secret.txt"})
                self.assertTrue(result.isError)


class AgentTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, request, tool_name):
        call = ChatCompletionMessage(role="assistant", content=None, tool_calls=[{
            "id": "call_1", "type": "function", "function": {"name": tool_name, "arguments": "{}"}}])
        final = ChatCompletionMessage(role="assistant", content="完成")
        client = MagicMock()
        client.__enter__.return_value = client
        client.chat.completions.create.side_effect = [
            SimpleNamespace(choices=[SimpleNamespace(message=call)]),
            SimpleNamespace(choices=[SimpleNamespace(message=final)])]
        session = SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(
            isError=False, content=[SimpleNamespace(type="text", text="工具结果")])) )
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": request}]
        with patch("agent.create_client", return_value=client), patch("agent.model_name", return_value="fake"):
            result = await run_turn(session, messages, [], trace=False)
        self.assertEqual(result, "完成")
        self.assertEqual(messages[-2]["tool_call_id"], "call_1")
        self.assertEqual(messages[-1]["role"], "assistant")
        return session, messages

    async def test_model_tool_result_roundtrip(self):
        session, messages = await self.exercise("查询知识库", "search_documents")
        session.call_tool.assert_awaited_once_with("search_documents", {})
        self.assertEqual(messages[-2]["content"], "工具结果")

    async def test_unsolicited_save_is_blocked(self):
        session, messages = await self.exercise("概括知识库内容", "save_note")
        session.call_tool.assert_not_awaited()
        self.assertIn("未明确请求保存", messages[-2]["content"])

    async def test_requested_save_is_allowed(self):
        session, messages = await self.exercise("请保存清单", "save_note")
        session.call_tool.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
