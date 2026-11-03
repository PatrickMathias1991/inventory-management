"""
Tests for task API endpoints.
"""
import pytest


class TestTaskEndpoints:
    """Test suite for task endpoints."""

    @staticmethod
    def payload(**overrides):
        data = {"title": "Check supplier invoices", "priority": "high", "dueDate": "2025-11-20"}
        data.update(overrides)
        return data

    def test_get_tasks_empty(self, client):
        """Test that no tasks exist before any are created."""
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_task(self, client):
        """Test creating a task."""
        response = client.post("/api/tasks", json=self.payload())
        assert response.status_code == 201

        task = response.json()
        assert task["id"].startswith("T-")
        assert task["title"] == "Check supplier invoices"
        assert task["priority"] == "high"
        assert task["dueDate"] == "2025-11-20"
        assert task["status"] == "pending"

    def test_create_task_trims_title(self, client):
        """Test that surrounding whitespace is stripped from the title."""
        task = client.post("/api/tasks", json=self.payload(title="  Call vendor  ")).json()
        assert task["title"] == "Call vendor"

    def test_task_ids_are_unique(self, client):
        """Test that ids stay unique, including after a deletion."""
        first = client.post("/api/tasks", json=self.payload()).json()
        client.delete(f"/api/tasks/{first['id']}")
        second = client.post("/api/tasks", json=self.payload()).json()
        assert first["id"] != second["id"]

    def test_get_tasks_newest_first(self, client):
        """Test that tasks are listed newest first."""
        first = client.post("/api/tasks", json=self.payload(title="First")).json()
        second = client.post("/api/tasks", json=self.payload(title="Second")).json()

        ids = [t["id"] for t in client.get("/api/tasks").json()]
        assert ids == [second["id"], first["id"]]

    @pytest.mark.parametrize("overrides", [
        {"title": "   "},
        {"priority": "urgent"},
        {"dueDate": "20/11/2025"},
        {"dueDate": ""},
    ])
    def test_create_task_invalid_input(self, client, overrides):
        """Test that invalid field values are rejected without creating a task."""
        response = client.post("/api/tasks", json=self.payload(**overrides))
        assert response.status_code == 400
        assert client.get("/api/tasks").json() == []

    def test_create_task_missing_fields(self, client):
        """Test that a request missing required fields fails validation."""
        response = client.post("/api/tasks", json={"title": "No priority"})
        assert response.status_code == 422

    def test_toggle_task(self, client):
        """Test that PATCH flips a task between pending and completed."""
        task_id = client.post("/api/tasks", json=self.payload()).json()["id"]

        completed = client.patch(f"/api/tasks/{task_id}")
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"

        reopened = client.patch(f"/api/tasks/{task_id}")
        assert reopened.json()["status"] == "pending"

    def test_toggle_nonexistent_task(self, client):
        """Test toggling a task that doesn't exist."""
        response = client.patch("/api/tasks/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_delete_task(self, client):
        """Test deleting a task."""
        task_id = client.post("/api/tasks", json=self.payload()).json()["id"]

        response = client.delete(f"/api/tasks/{task_id}")
        assert response.status_code == 204
        assert client.get("/api/tasks").json() == []

    def test_delete_nonexistent_task(self, client):
        """Test deleting a task that doesn't exist."""
        response = client.delete("/api/tasks/nonexistent-999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
