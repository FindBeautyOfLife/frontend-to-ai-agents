"""命令行入口：完整知识库助手，以及独立的模型、检索和工具发现模式。"""

import argparse
import asyncio
import builtins
import sys

from openai import APIConnectionError, APIStatusError, APITimeoutError

from agent import SYSTEM_PROMPT, run_turn, tool_schemas, trim_history
from config import create_client, model_name
from knowledge_service import search_knowledge
from mcp_connection import connect_tools


def parse_args():
    parser = argparse.ArgumentParser(description="本地知识库助手：LLM + MCP + RAG")
    parser.add_argument("question", nargs="?", help="单次提问；不传则进入多轮对话")
    parser.add_argument("--search", choices=("vector", "keyword"), default="vector")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--retrieve-only", action="store_true", help="只检索；vector 模式仍调用 embedding")
    modes.add_argument("--llm-only", action="store_true", help="只调用聊天模型")
    modes.add_argument("--list-tools", action="store_true", help="通过 MCP 协议列出工具，不调用 LLM")
    parser.add_argument("--quiet", action="store_true", help="隐藏工具调用过程")
    return parser.parse_args()


def get_question(question):
    value = question if question is not None else input("你：")
    if not value.strip():
        raise ValueError("问题不能为空。")
    return value.strip()


async def main():
    args = parse_args()
    if args.retrieve_only:
        result = await asyncio.to_thread(search_knowledge, get_question(args.question), args.search)
        for source in result["sources"]:
            print(f"[{source['id']}] {source['source']} 相似度：{source['score']}")
        print(result["context"] or result["message"])
        return
    if args.llm_only:
        question = get_question(args.question)
        with create_client() as client:
            result = await asyncio.to_thread(client.chat.completions.create, model=model_name(),
                messages=[{"role": "system", "content": "请用中文简明回答。"},
                          {"role": "user", "content": question}])
        if not result.choices or not result.choices[0].message.content:
            raise ValueError("模型没有返回文本回答。")
        print("助手：" + result.choices[0].message.content)
        return

    # MCP 服务由客户端自动启动，无需用户手动打开第二个终端。
    async with connect_tools() as session:
        listed = (await session.list_tools()).tools
        if args.list_tools:
            for tool in listed:
                print(f"{tool.name}: {tool.description}")
            return
        model_name()
        schemas = tool_schemas(listed)
        messages = [{"role": "system", "content": SYSTEM_PROMPT.format(mode=args.search)}]
        if args.question is not None:
            messages.append({"role": "user", "content": get_question(args.question)})
            print("助手：" + await run_turn(session, messages, schemas, not args.quiet))
            return
        print("本地知识库助手已启动。输入 /exit 退出，/clear 清空对话，/tools 查看工具。")
        while True:
            try:
                question = (await asyncio.to_thread(input, "\n你：")).strip()
            except EOFError:
                break
            if question in {"/exit", "exit", "quit"}:
                break
            if question == "/clear":
                messages = messages[:1]
                print("对话已清空。")
                continue
            if question == "/tools":
                print("\n".join(tool.name for tool in listed))
                continue
            if not question:
                continue
            messages.append({"role": "user", "content": question})
            trim_history(messages)
            print("助手：" + await run_turn(session, messages, schemas, not args.quiet))


def report_error(error: Exception) -> str:
    # TaskGroup 会包装子进程错误；不打印可能带敏感配置的原始服务响应。
    # 识别异常组后逐项转换为排错提示，避免直接输出嵌套异常详情。
    exception_group_type = getattr(builtins, "BaseExceptionGroup", ())
    if isinstance(error, exception_group_type):
        return "；".join(dict.fromkeys(report_error(item) for item in error.exceptions))
    if isinstance(error, APITimeoutError):
        return "请求超时，请稍后重试。"
    if isinstance(error, APIConnectionError):
        return "连接失败，请检查网络和 BAILIAN_BASE_URL。"
    if isinstance(error, APIStatusError):
        return f"模型服务返回 HTTP {error.status_code}，请检查模型权限、额度及工具调用支持。"
    if isinstance(error, UnicodeError):
        return "文档编码错误，请保存为 UTF-8。"
    if isinstance(error, OSError):
        return "文件或进程操作失败，请检查路径、权限及依赖安装。"
    if isinstance(error, ValueError):
        return "配置、输入或模型返回格式有误，请检查 .env 和命令参数。"
    return "MCP 或模型调用失败，请检查依赖、服务配置及模型的工具调用支持。"


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出。")
    except Exception as error:
        print("错误：" + report_error(error), file=sys.stderr)
        sys.exit(1)
