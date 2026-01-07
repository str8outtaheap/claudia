"""MCP tools for task management."""

import json
import re
from datetime import datetime, timedelta

from claude_agent_sdk import tool, create_sdk_mcp_server
from datetime_utils import now_cet
from storage import TaskStorage


def _schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": []}


def _json_response(payload: dict, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    if is_error:
        result["is_error"] = True
    return result


def create_task_server(storage: TaskStorage):
    """Create MCP server with all task tools bound to a storage instance."""
    relative_pattern = re.compile(
        r"(?:in\s+)?(\d+)\s*(seconds?|minutes?|hours?|days?)",
        re.IGNORECASE,
    )
    tomorrow_pattern = re.compile(r"\btomorrow\b", re.IGNORECASE)
    time_pattern = re.compile(
        r"(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", re.IGNORECASE
    )

    def normalize_remind_at(remind_at: str) -> tuple[str | None, str | None]:
        raw = remind_at.strip()
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed.isoformat(), None
        except ValueError:
            pass

        now = now_cet().replace(tzinfo=None)
        rel_match = relative_pattern.search(raw)
        if rel_match:
            amount = int(rel_match.group(1))
            unit = rel_match.group(2).lower()
            delta = timedelta(seconds=amount)
            if unit.startswith("minute"):
                delta = timedelta(minutes=amount)
            elif unit.startswith("hour"):
                delta = timedelta(hours=amount)
            elif unit.startswith("day"):
                delta = timedelta(days=amount)
            return (now + delta).isoformat(), None

        if tomorrow_pattern.search(raw):
            target = now + timedelta(days=1)
            time_match = time_pattern.search(raw)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                meridiem = (time_match.group(3) or "").lower()
                if meridiem == "pm" and hour < 12:
                    hour += 12
                if meridiem == "am" and hour == 12:
                    hour = 0
                target = target.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                target = target.replace(
                    hour=now.hour, minute=now.minute, second=0, microsecond=0
                )
            return target.isoformat(), None

        return None, "remind_at must be ISO 8601 or a relative time (e.g., 'in 5 minutes')"

    @tool(
        "add_task",
        "Add a new task to the list",
        _schema({"title": {"type": "string"}, "priority": {"type": "string"}}),
    )
    async def add_task(args: dict) -> dict:
        """Add a new task with title and priority."""
        title = args.get("title", "")
        priority = args.get("priority", "medium")

        if not title:
            return _json_response(
                {"ok": False, "error": "Task title is required"}, is_error=True
            )

        if priority not in ("low", "medium", "high"):
            priority = "medium"

        task = storage.add_task(title, priority)
        return _json_response({"ok": True, "task": task})

    @tool(
        "schedule_reminder",
        "Schedule a reminder for a task by ID or title. Use ISO 8601 or relative time (e.g., 'in 5 minutes').",
        _schema(
            {
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "remind_at": {"type": "string"},
            }
        ),
    )
    async def schedule_reminder(args: dict) -> dict:
        """Schedule a reminder."""
        task_id = args.get("task_id", "")
        title = args.get("title", "")
        remind_at = args.get("remind_at", "")

        if not remind_at:
            return _json_response(
                {"ok": False, "error": "remind_at is required"}, is_error=True
            )

        remind_at, error = normalize_remind_at(remind_at)
        if error:
            return _json_response({"ok": False, "error": error}, is_error=True)

        if task_id:
            task = storage.set_reminder(task_id, remind_at)
            if not task:
                return _json_response(
                    {"ok": False, "error": f"Task {task_id} not found"},
                    is_error=True,
                )
        else:
            if not title:
                return _json_response(
                    {"ok": False, "error": "title is required"}, is_error=True
                )
            task = storage.add_task(title, "medium", remind_at)

        return _json_response({"ok": True, "task": task, "remind_at": remind_at})

    @tool(
        "set_daily_summary",
        "Configure daily summary time (CET). Use HH:MM (24h) or 'off'.",
        _schema({"time": {"type": "string"}}),
    )
    async def set_daily_summary(args: dict) -> dict:
        value = (args.get("time") or "").strip().lower()
        if not value:
            return _json_response(
                {"ok": False, "error": "time is required"}, is_error=True
            )

        if value in ("off", "disable", "disabled", "none"):
            storage.set_daily_summary_time(None)
            return _json_response({"ok": True, "daily_summary_time": None})

        if not re.match(r"^\\d{2}:\\d{2}$", value):
            return _json_response(
                {"ok": False, "error": "time must be HH:MM (24h) or 'off'"},
                is_error=True,
            )

        hours, minutes = value.split(":")
        hour = int(hours)
        minute = int(minutes)
        if hour > 23 or minute > 59:
            return _json_response(
                {"ok": False, "error": "time must be valid HH:MM"},
                is_error=True,
            )

        storage.set_daily_summary_time(f"{hour:02d}:{minute:02d}")
        return _json_response(
            {"ok": True, "daily_summary_time": f"{hour:02d}:{minute:02d}"}
        )

    @tool(
        "list_tasks",
        "List tasks. Filter by status: 'pending', 'completed', or 'all'",
        _schema({"status": {"type": "string"}}),
    )
    async def list_tasks(args: dict) -> dict:
        """List tasks filtered by status."""
        status = args.get("status", "pending")
        tasks = storage.list_tasks(status)

        return _json_response({"ok": True, "status": status, "tasks": tasks})

    @tool(
        "complete_task",
        "Mark a task as completed by its ID",
        _schema({"task_id": {"type": "string"}}),
    )
    async def complete_task(args: dict) -> dict:
        """Mark a task as complete."""
        task_id = args.get("task_id", "")

        if not task_id:
            return _json_response(
                {"ok": False, "error": "Task ID is required"}, is_error=True
            )

        task = storage.complete_task(task_id)
        if task:
            return _json_response({"ok": True, "task": task})
        return _json_response(
            {"ok": False, "error": f"Task {task_id} not found"}, is_error=True
        )

    @tool(
        "delete_task",
        "Delete a task by its ID",
        _schema({"task_id": {"type": "string"}}),
    )
    async def delete_task(args: dict) -> dict:
        """Delete a task."""
        task_id = args.get("task_id", "")

        if not task_id:
            return _json_response(
                {"ok": False, "error": "Task ID is required"}, is_error=True
            )

        task = storage.delete_task(task_id)
        if task:
            return _json_response({"ok": True, "task": task})
        return _json_response(
            {"ok": False, "error": f"Task {task_id} not found"}, is_error=True
        )

    @tool(
        "get_summary",
        "Get a summary of all tasks and statistics",
        _schema({}),
    )
    async def get_summary(args: dict) -> dict:
        """Get task statistics."""
        summary = storage.get_summary()
        return _json_response({"ok": True, "summary": summary})

    @tool(
        "clear_reminders",
        "Clear all reminders from tasks",
        _schema({}),
    )
    async def clear_reminders(args: dict) -> dict:
        cleared = storage.clear_reminders()
        return _json_response({"ok": True, "cleared": cleared})

    return create_sdk_mcp_server(
        name="task-manager",
        version="1.0.0",
        tools=[
            add_task,
            list_tasks,
            complete_task,
            delete_task,
            get_summary,
            schedule_reminder,
            set_daily_summary,
            clear_reminders,
        ],
    )
