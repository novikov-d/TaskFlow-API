"""Автоматические тесты TaskFlow API."""

import pytest
from fastapi.testclient import TestClient

from app_final import app


@pytest.fixture
def client():
    # Каждый тест получает пустое хранилище благодаря lifespan.
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version(client):
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["version"] == app.version


def test_empty_task_list(client):
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_create_and_get_task(client):
    created = client.post("/tasks", json={"title": "Подготовиться к зачёту"})
    assert created.status_code == 201
    task = created.json()
    assert task["id"] == 1
    assert task["title"] == "Подготовиться к зачёту"
    assert task["completed"] is False
    assert task["created_at"]

    fetched = client.get("/tasks/1")
    assert fetched.status_code == 200
    assert fetched.json() == task


def test_reject_blank_title(client):
    response = client.post("/tasks", json={"title": "   "})
    assert response.status_code == 422


def test_missing_task_returns_404(client):
    response = client.get("/tasks/999")
    assert response.status_code == 404


def test_update_task_and_statistics(client):
    client.post("/tasks", json={"title": "Первая"})
    client.post("/tasks", json={"title": "Вторая"})

    response = client.patch("/tasks/1", json={"completed": True, "title": "Готово"})
    assert response.status_code == 200
    assert response.json()["completed"] is True
    assert response.json()["title"] == "Готово"

    stats = client.get("/tasks/stats")
    assert stats.status_code == 200
    assert stats.json() == {"total": 2, "completed": 1, "pending": 1}


def test_filter_tasks_by_completion(client):
    client.post("/tasks", json={"title": "Первая"})
    client.post("/tasks", json={"title": "Вторая"})
    client.patch("/tasks/2", json={"completed": True})

    result = client.get("/tasks?completed=true")
    assert result.status_code == 200
    assert [task["id"] for task in result.json()] == [2]


def test_delete_task(client):
    client.post("/tasks", json={"title": "Удалить"})
    response = client.delete("/tasks/1")
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/tasks/1").status_code == 404


def test_empty_update_returns_400(client):
    client.post("/tasks", json={"title": "Задача"})
    assert client.patch("/tasks/1", json={}).status_code == 400


def test_reject_null_update(client):
    client.post("/tasks", json={"title": "Задача"})
    assert client.patch("/tasks/1", json={"title": None}).status_code == 422


def test_limit_from_environment(monkeypatch):
    monkeypatch.setenv("MAX_TASKS", "1")
    with TestClient(app) as client:
        assert client.post("/tasks", json={"title": "Первая"}).status_code == 201
        response = client.post("/tasks", json={"title": "Вторая"})
        assert response.status_code == 409
        assert response.json()["detail"] == "Достигнут лимит задач"
