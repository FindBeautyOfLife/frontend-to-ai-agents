# FastAPI 任务管理示例

用 Python 提供任务接口，并由 `index.html` 使用 `fetch` 调用。建议先完成阶段 01，理解 DOM 操作与事件监听。

## 学习目标

这一阶段把任务数据从浏览器页面移到 Python 进程中。重点是跟踪一次完整请求：页面读取输入，发送 JSON，后端校验并更新任务，页面重新获取列表并渲染。

阅读前需要了解 Python 函数、列表和字典。FastAPI 用于定义 HTTP 接口，Pydantic 请求模型用于描述和校验输入数据。

## 启动

在本目录执行（Python 3.11+）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

打开 <http://127.0.0.1:8000> 使用页面，打开 <http://127.0.0.1:8000/docs> 查看交互式接口文档。页面需要通过后端访问，直接打开 HTML 文件无法使用相对路径的接口。

页面初始显示两条学习任务。新增一条任务，勾选完成，再将它删除；页面列表和统计数字应随之更新。终端按 `Ctrl+C` 停止服务。

## 接口与阅读顺序

| 请求 | 用途 |
| --- | --- |
| `GET /` | 返回前端页面 |
| `GET /tasks` | 获取任务列表 |
| `POST /tasks` | 新增任务，请求体示例：`{"name": "学习 FastAPI"}` |
| `PATCH /tasks/{task_id}` | 更新完成状态，请求体示例：`{"completed": true}` |
| `DELETE /tasks/{task_id}` | 删除任务 |

## 对照代码阅读

1. 阅读 `main.py` 的 `TaskCreate` 和 `TaskUpdate`，了解请求体有哪些字段；再看 `tasks` 和 `next_id` 如何保存状态和分配编号。
2. 对照上表阅读五个路由。`@app.get()` 等装饰器将 HTTP 方法和路径映射到 Python 函数。
3. 打开 `index.html`，从 `addTask()` 跟踪新增请求：`JSON.stringify()` 序列化输入，`fetch()` 发送请求，`checkResponse()` 检查状态码，`loadTasks()` 重新拉取并显示列表。
4. 查看完成状态与删除按钮的事件处理，对比 `PATCH`、`DELETE` 与新增请求的区别。

新增成功返回 HTTP 201；无效输入返回 422；更新或删除不存在的任务返回 404。前端会检查非成功响应并显示错误提示。

## 动手练习

- 在浏览器开发者工具的 Network 面板中添加一条任务，查看 `POST /tasks` 的请求体和响应，以及随后发生的 `GET /tasks`。
- 刷新页面，观察任务仍在；重启后端，再观察任务恢复为初始数据。解释这与阶段 01 刷新页面就丢失数据有什么区别。
- 在 `/docs` 中提交空白任务名称，或删除一个不存在的任务编号，对照后端分支观察响应状态。

## 示例边界与下一步

任务存放在进程内的列表中，重启服务或触发自动重载后会恢复示例数据；不适用于多进程共享。示例没有身份认证，仅用于本地学习。

下一步阅读 [阶段 03](../03LLM%2BTool%20Calling/README.md)。它使用独立的商店助手示例，展示模型如何生成结构化请求，再由 Python 函数执行；无需保持本阶段服务运行。
