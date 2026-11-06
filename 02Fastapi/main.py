
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI()

# 示例数据保存在进程内存中；服务重启后重置，不在多个进程间共享。
tasks = [
    {"id": 1, "name": "学习 JavaScript", "completed": True},
    {"id": 2, "name": "学习 FastAPI", "completed": False}
]

next_id = 3


# 请求体由 Pydantic 校验；空白字符串还需在路由中 strip 后检查。
class TaskCreate(BaseModel):
    name: str = Field(min_length=1)


class TaskUpdate(BaseModel):
    completed: bool


# 页面和接口由同一个服务提供，前端可直接请求 /tasks 等相对路径。
@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


# 返回列表后，FastAPI 会将 Python 数据序列化为 JSON。
@app.get("/tasks")
def get_tasks():
    return tasks


# 新任务由服务端分配 ID，客户端只需提交名称。
@app.post("/tasks", status_code=201)
def add_task(task: TaskCreate):
    global next_id

    name = task.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="任务名称不能为空")

    new_task = {
        "id": next_id,
        "name": name,
        "completed": False
    }

    next_id += 1
    tasks.append(new_task)

    return new_task


# 通过稳定的任务 ID 查找数据，避免将列表位置当作身份标识。
@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    for task in tasks:
        if task["id"] == task_id:
            tasks.remove(task)
            return {"message": "删除成功"}

    raise HTTPException(status_code=404, detail="任务不存在")


# PATCH 请求只传入要修改的完成状态，任务名称和 ID 保持原值。
@app.patch("/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdate):
    for task in tasks:
        if task["id"] == task_id:
            task["completed"] = update.completed
            return task

    raise HTTPException(status_code=404, detail="任务不存在")
