"""TaskFlow API: простой сервис для управления задачами.

Данные хранятся в оперативной памяти и сбрасываются при перезапуске.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "TaskFlow API")
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("taskflow")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

TaskTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class TaskCreate(BaseModel):
    title: TaskTitle = Field(description="Название задачи")
    description: str = Field(default="", max_length=500)


class TaskUpdate(BaseModel):
    title: TaskTitle | None = None
    description: str | None = Field(default=None, max_length=500)
    completed: bool | None = None


class Task(TaskCreate):
    id: int
    completed: bool = False
    created_at: datetime


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Подготавливает хранилище и проверяет настройки при запуске."""
    try:
        limit = int(os.getenv("MAX_TASKS", "100"))
    except ValueError as exc:
        logger.error("MAX_TASKS должен быть целым положительным числом")
        raise ValueError("MAX_TASKS должен быть целым положительным числом") from exc

    if limit <= 0:
        logger.error("MAX_TASKS должен быть больше нуля")
        raise ValueError("MAX_TASKS должен быть больше нуля")

    application.state.tasks = {}
    application.state.next_id = 1
    application.state.max_tasks = limit
    logger.info("Сервис %s (версия %s) запущен; лимит задач: %s", APP_NAME, APP_VERSION, limit)
    yield
    logger.info("Сервис %s остановлен", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    description="Учебный REST API для создания, просмотра и управления задачами.",
    version=APP_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Ошибка обработки запроса %s %s", request.method, request.url.path)
        raise
    logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.get("/", tags=["Сервис"])
def home():
    return {"service": APP_NAME, "docs": "/docs"}


@app.get("/health", tags=["Сервис"])
def health():
    return {"status": "ok"}


@app.get("/version", tags=["Сервис"])
def version():
    return {"version": APP_VERSION}


@app.get("/tasks", response_model=list[Task], tags=["Задачи"])
def list_tasks(request: Request, completed: bool | None = None):
    """Возвращает все задачи или отфильтрованные по готовности."""
    tasks = list(request.app.state.tasks.values())
    if completed is not None:
        tasks = [task for task in tasks if task.completed == completed]
    return tasks


@app.post("/tasks", response_model=Task, status_code=status.HTTP_201_CREATED, tags=["Задачи"])
def create_task(data: TaskCreate, request: Request):
    """Создаёт новую задачу, если не достигнут лимит MAX_TASKS."""
    tasks = request.app.state.tasks
    if len(tasks) >= request.app.state.max_tasks:
        logger.warning("Превышен лимит задач: %s", request.app.state.max_tasks)
        raise HTTPException(status_code=409, detail="Достигнут лимит задач")

    task_id = request.app.state.next_id
    task = Task(
        id=task_id,
        title=data.title,
        description=data.description,
        completed=False,
        created_at=datetime.now(timezone.utc),
    )
    tasks[task_id] = task
    request.app.state.next_id += 1
    logger.info("Создана задача id=%d", task_id)
    return task


@app.get("/tasks/stats", tags=["Задачи"])
def task_stats(request: Request):
    """Показывает количество всех, выполненных и открытых задач."""
    tasks = list(request.app.state.tasks.values())
    completed = sum(task.completed for task in tasks)
    return {"total": len(tasks), "completed": completed, "pending": len(tasks) - completed}


def find_task(request: Request, task_id: int) -> Task:
    task = request.app.state.tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


@app.get("/tasks/{task_id}", response_model=Task, tags=["Задачи"])
def get_task(task_id: int, request: Request):
    return find_task(request, task_id)


@app.patch("/tasks/{task_id}", response_model=Task, tags=["Задачи"])
def update_task(task_id: int, data: TaskUpdate, request: Request):
    """Частично изменяет название, описание или статус задачи."""
    task = find_task(request, task_id)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Передайте хотя бы одно поле")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Поля нельзя устанавливать в null")

    updated = task.model_copy(update=changes)
    request.app.state.tasks[task_id] = updated
    logger.info("Обновлена задача id=%d, поля=%s", task_id, list(changes))
    return updated


@app.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Задачи"])
def delete_task(task_id: int, request: Request):
    find_task(request, task_id)
    del request.app.state.tasks[task_id]
    logger.info("Удалена задача id=%d", task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
