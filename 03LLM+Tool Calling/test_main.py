"""离线验证工具与消息协议，不读取 .env，也不调用真实 API。"""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


def tool_call(call_id="call_1", order_id="A1001", *, name="get_order_status", arguments=None):
    data = {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps({"order_id": order_id} if arguments is None else arguments),
        },
    }
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(**data["function"]),
        model_dump=lambda: copy.deepcopy(data),
    )


def response(content=None, calls=None):
    message = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class ToolCallingTests(unittest.TestCase):
    def setUp(self):
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)

    def test_lookup_and_missing_order(self):
        self.assertEqual(main.get_order_status(" a1001 ")["status"], "已发货")
        self.assertFalse(main.get_order_status("A9999")["found"])

    def test_invalid_tool_requests_return_errors(self):
        for name, arguments in [
            ("unknown", '{}'),
            ("get_order_status", '{broken'),
            ("get_order_status", '[]'),
            ("get_order_status", '{}'),
            ("get_order_status", '{"order_id": 123}'),
            ("get_order_status", '{"order_id": ""}'),
            ("get_order_status", '{"order_id": "A1001", "extra": true}'),
        ]:
            with self.subTest(name=name, arguments=arguments):
                result = json.loads(main.execute_tool(name, arguments))
                self.assertIn("error", result)

    def test_file_failure_returns_tool_error(self):
        output = io.StringIO()
        with patch.object(main, "ORDERS_FILE") as orders_file:
            orders_file.read_text.side_effect = OSError(13, "private-error-detail", "private-demo-orders.json")
            with redirect_stdout(output):
                result = json.loads(main.execute_tool("get_order_status", '{"order_id":"A1001"}'))
        self.assertIn("演示数据读取失败", result["error"])
        for private_detail in ("private-error-detail", "private-demo-orders.json"):
            self.assertNotIn(private_detail, json.dumps(result))
            self.assertNotIn(private_detail, output.getvalue())

    def test_multiple_calls_are_sent_back_before_next_request(self):
        requests = []
        responses = iter([
            response(calls=[tool_call("call_1"), tool_call("call_2", "A1002")]),
            response(content="A1001 已发货，A1002 待发货。"),
        ])

        def create(**kwargs):
            requests.append(copy.deepcopy(kwargs))
            return next(responses)

        client = Mock()
        client.chat.completions.create.side_effect = create
        messages = [{"role": "user", "content": "查一下 A1001 和 A1002"}]
        answer = main.chat_with_tools(client, "test-model", messages)

        self.assertIn("已发货", answer)
        self.assertEqual(len(requests), 2)
        self.assertEqual([m["role"] for m in requests[1]["messages"]],
                         ["user", "assistant", "tool", "tool"])
        tool_messages = requests[1]["messages"][2:]
        self.assertEqual([m["tool_call_id"] for m in tool_messages], ["call_1", "call_2"])
        self.assertEqual(json.loads(tool_messages[0]["content"])["status"], "已发货")
        self.assertEqual(json.loads(tool_messages[1]["content"])["status"], "待发货")
        self.assertEqual(messages[-1], {"role": "assistant", "content": answer})

    def test_normal_chat_does_not_execute_tool(self):
        client = Mock()
        client.chat.completions.create.return_value = response(content="你好！")
        with patch.object(main, "execute_tool") as execute:
            self.assertEqual(main.chat_with_tools(client, "test-model", []), "你好！")
        execute.assert_not_called()
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_limit_disables_tools_for_final_answer(self):
        client = Mock()
        client.chat.completions.create.side_effect = [
            response(calls=[tool_call()]) for _ in range(main.MAX_TOOL_ROUNDS)
        ] + [response(content="已完成查询。")]
        self.assertEqual(main.chat_with_tools(client, "test-model", []), "已完成查询。")
        self.assertEqual(client.chat.completions.create.call_args.kwargs["tool_choice"], "none")

    def test_limit_rejects_further_tool_calls(self):
        client = Mock()
        client.chat.completions.create.return_value = response(calls=[tool_call()])
        with self.assertRaisesRegex(RuntimeError, "次数已达上限"):
            main.chat_with_tools(client, "test-model", [])
        self.assertEqual(client.chat.completions.create.call_count, main.MAX_TOOL_ROUNDS + 1)

    def test_empty_model_response_fails_clearly(self):
        client = Mock()
        client.chat.completions.create.return_value = response()
        with self.assertRaisesRegex(RuntimeError, "既未返回内容"):
            main.chat_with_tools(client, "test-model", [])


    def test_product_search_and_details(self):
        result = main.search_products("鼠标", max_price=80)
        self.assertEqual([p["product_id"] for p in result["products"]], ["P1002"])
        self.assertEqual(main.search_products("不存在的商品")["count"], 0)
        self.assertEqual(main.search_products("外设")["count"], 3)
        order = main.get_order_status("A1001")
        product = main.get_product_details(order["product_id"])
        self.assertEqual(product["name"], order["product"])
        self.assertIn("连接方式", product["specs"])
        self.assertFalse(main.get_product_details("missing")["found"])

    def test_quote_shipping_threshold_and_remote_region(self):
        normal = main.calculate_order_total("P1002", 2, "上海")
        self.assertEqual(normal["subtotal_yuan"], 158)
        self.assertEqual(normal["shipping_yuan"], 8)
        self.assertEqual(normal["total_yuan"], 166)
        free = main.calculate_order_total("P1001", 1, "上海")
        self.assertEqual(free["shipping_yuan"], 0)
        self.assertEqual(free["total_yuan"], 199)
        remote = main.calculate_order_total("P1001", 1, "新疆")
        self.assertEqual(remote["shipping_yuan"], 20)
        self.assertEqual(remote["total_yuan"], 219)

    def test_quote_refuses_unavailable_stock_or_region(self):
        for product_id, quantity, destination in [
            ("P1004", 1, "上海"), ("P1001", 13, "上海"),
            ("missing", 1, "上海"), ("P1001", 1, "未知地区"),
        ]:
            with self.subTest(product_id=product_id, quantity=quantity, destination=destination):
                self.assertFalse(main.calculate_order_total(product_id, quantity, destination)["quotable"])

    def test_new_tools_validate_arguments(self):
        cases = [
            ("search_products", {"keyword": " "}),
            ("search_products", {"keyword": "鼠标", "max_price": True}),
            ("search_products", {"keyword": "鼠标", "max_price": -1}),
            ("search_products", {"keyword": "鼠标", "max_price": float("nan")}),
            ("get_product_details", {"product_id": 12}),
            ("get_product_details", {"product_id": "P1001", "extra": 1}),
            ("calculate_order_total", {"product_id": "P1001", "quantity": 1}),
            ("get_after_sales_policy", {"topic": "unknown"}),
        ]
        cases += [("calculate_order_total", {"product_id": "P1001", "quantity": quantity,
                                             "destination": "上海"})
                  for quantity in [True, 0, -1, 100, 1.5, "2"]]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                self.assertIn("error", json.loads(main.execute_tool(name, json.dumps(arguments))))

    def test_policy_topics_and_registry_match(self):
        for topic in ["return", "exchange", "warranty"]:
            self.assertIn("description", main.get_after_sales_policy(topic)["policy"])
        self.assertEqual({tool["function"]["name"] for tool in main.TOOLS}, set(main.TOOL_FUNCTIONS))

    def test_search_then_quote_across_model_rounds(self):
        requests = []
        responses = iter([
            response(calls=[tool_call(name="search_products", arguments={"keyword": "无线鼠标"})]),
            response(calls=[tool_call("call_quote", name="calculate_order_total", arguments={
                "product_id": "P1002", "quantity": 2, "destination": "上海",
            })]),
            response(content="演示报价：两只无线鼠标寄到上海共 166 元，含运费 8 元。"),
        ])

        def create(**kwargs):
            requests.append(copy.deepcopy(kwargs))
            return next(responses)

        client = Mock()
        client.chat.completions.create.side_effect = create
        messages = [{"role": "user", "content": "两只无线鼠标寄到上海多少钱？"}]
        self.assertIn("166", main.chat_with_tools(client, "test-model", messages))
        self.assertEqual(len(requests), 3)
        search_result = json.loads(requests[1]["messages"][-1]["content"])
        self.assertEqual(search_result["products"][0]["product_id"], "P1002")
        quote_message = requests[2]["messages"][-1]
        self.assertEqual(quote_message["tool_call_id"], "call_quote")
        self.assertEqual(json.loads(quote_message["content"])["total_yuan"], 166)


if __name__ == "__main__":
    unittest.main()
