"""Task storage using JSON file persistence."""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional
import uuid


class TaskStorage:
    def __init__(self, file_path: str = "tasks.json", settings_path: str | None = None):
        self.file_path = Path(file_path)
        if settings_path is None:
            if self.file_path.stem.startswith("tasks_"):
                settings_name = self.file_path.stem.replace("tasks_", "settings_", 1)
                settings_path = f"{settings_name}.json"
            else:
                settings_path = "settings.json"
        self.settings_path = Path(settings_path)
        self.tasks: list[dict] = []
        self.settings: dict = {}
        self.load()
        self.load_settings()

    def load(self) -> None:
        """Load tasks from JSON file."""
        if self.file_path.exists():
            with open(self.file_path, "r") as f:
                self.tasks = json.load(f)
        else:
            self.tasks = []

    def save(self) -> None:
        """Save tasks to JSON file."""
        with open(self.file_path, "w") as f:
            json.dump(self.tasks, f, indent=2)

    def load_settings(self) -> None:
        """Load settings from JSON file."""
        if self.settings_path.exists():
            with open(self.settings_path, "r") as f:
                self.settings = json.load(f)
        else:
            self.settings = {}

    def save_settings(self) -> None:
        """Save settings to JSON file."""
        with open(self.settings_path, "w") as f:
            json.dump(self.settings, f, indent=2)

    def get_daily_summary_time(self) -> Optional[str]:
        return self.settings.get("daily_summary_time")

    def set_daily_summary_time(self, value: Optional[str]) -> None:
        if value:
            self.settings["daily_summary_time"] = value
        else:
            self.settings.pop("daily_summary_time", None)
        self.save_settings()

    def add_task(
        self,
        title: str,
        priority: str = "medium",
        remind_at: str | None = None,
    ) -> dict:
        """Add a new task."""
        task = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "priority": priority.lower(),
            "status": "pending",
            "remind_at": remind_at,
            "reminded_at": None,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
        }
        self.tasks.append(task)
        self.save()
        return task

    def list_tasks(self, status: str = "all") -> list[dict]:
        """List tasks filtered by status."""
        if status == "all":
            return self.tasks
        return [t for t in self.tasks if t["status"] == status]

    def complete_task(self, task_id: str) -> Optional[dict]:
        """Mark a task as complete."""
        for task in self.tasks:
            if task["id"] == task_id:
                task["status"] = "completed"
                task["completed_at"] = datetime.now().isoformat()
                self.save()
                return task
        return None

    def set_reminder(self, task_id: str, remind_at: str) -> Optional[dict]:
        """Attach a reminder time to a task."""
        for task in self.tasks:
            if task["id"] == task_id:
                task["remind_at"] = remind_at
                task["reminded_at"] = None
                self.save()
                return task
        return None

    def mark_reminded(self, task_id: str) -> None:
        """Mark a reminder as sent."""
        for task in self.tasks:
            if task["id"] == task_id:
                task["reminded_at"] = datetime.now().isoformat()
                self.save()
                return

    def clear_reminders(self) -> int:
        """Clear all reminder fields."""
        cleared = 0
        for task in self.tasks:
            if task.get("remind_at") or task.get("reminded_at"):
                task["remind_at"] = None
                task["reminded_at"] = None
                cleared += 1
        if cleared:
            self.save()
        return cleared

    def delete_task(self, task_id: str) -> Optional[dict]:
        """Delete a task by ID."""
        for i, task in enumerate(self.tasks):
            if task["id"] == task_id:
                deleted = self.tasks.pop(i)
                self.save()
                return deleted
        return None

    def get_summary(self) -> dict:
        """Get task statistics."""
        pending = [t for t in self.tasks if t["status"] == "pending"]
        completed = [t for t in self.tasks if t["status"] == "completed"]

        high_priority = [t for t in pending if t["priority"] == "high"]

        return {
            "total": len(self.tasks),
            "pending": len(pending),
            "completed": len(completed),
            "high_priority_pending": len(high_priority),
        }
