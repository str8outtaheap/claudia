#!/usr/bin/env python3
"""Daily Assistant - Telegram bot wrapper using Claude Agent SDK."""

import asyncio
import os
import re
from datetime import datetime, time
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from telegram import Message, Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)
from task_tools import create_task_server
from datetime_utils import CET_TZ, now_cet
from grocery_storage import GroceryStorage
from grocery_tools import create_grocery_server
from storage import TaskStorage
from workout_storage import WorkoutStorage
from workout_tools import create_workout_server

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = """You are a helpful daily task assistant. You help users manage their tasks efficiently.

Available actions:
- Add new tasks with priorities (low, medium, high)
- List pending, completed, or all tasks
- Mark tasks as complete
- Delete tasks
- Show task summary/statistics
- Schedule reminders for tasks
- Send a daily summary
- Log strength workouts
- Manage a grocery list

Be concise and helpful. When users mention completing or finishing a task, use the complete_task tool.
When they want to add something, use add_task. Infer priority from context if not specified.
When they ask for reminders or timing, use schedule_reminder with ISO 8601 or relative times (e.g., "in 5 minutes", "tomorrow").
When they ask to remove reminders, use clear_reminders.
When they ask to set a daily summary, use set_daily_summary with HH:MM (CET) or "off".
When they want to log workouts, use log_workout with exercises and sets. Log each exercise as its own entry. Default weight unit to kg.
If workout details are missing, ask a quick follow-up before logging.
When they want to edit a logged exercise, use edit_workout. When they want to remove one, use remove_exercise.
When they ask to list workouts, use list_workouts. For progress, use workout_summary (weight change and %) and pass the exercise name if specified.
When they mention groceries or a grocery list, use the grocery tools to add, list, remove, or clear items.
Always confirm actions taken.
Do not use emojis.
When listing tasks, use [ ] for pending, [x] for completed, and [HIGH]/[MED]/[LOW] for priority.
Tool responses are JSON. Parse them and respond with a concise, user-friendly summary. Do not show raw JSON.
"""

WAKE_WORD_RE = re.compile(r"^\s*claudia\b[:,]?\s*", re.IGNORECASE)


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else {}
    chat_id = data.get("chat_id")
    task_id = data.get("task_id")
    remind_at = data.get("remind_at")
    if chat_id is None or not task_id or not remind_at:
        return

    storages: Dict[int, TaskStorage] = context.application.bot_data["storages"]
    storage = storages.get(chat_id)
    if not storage:
        return

    task = next((t for t in storage.tasks if t["id"] == task_id), None)
    if not task:
        return
    if task.get("reminded_at") or task.get("status") == "completed":
        return
    if task.get("remind_at") != remind_at:
        return

    await context.bot.send_message(chat_id=chat_id, text=f"Reminder: {task['title']}")
    storage.mark_reminded(task_id)

    reminder_jobs: Dict[tuple[int, str], object] = context.application.bot_data[
        "reminder_jobs"
    ]
    reminder_jobs.pop((chat_id, task_id), None)


class ChatSession:
    def __init__(
        self,
        task_storage: TaskStorage,
        workout_storage: WorkoutStorage,
        grocery_storage: GroceryStorage,
    ):
        self._options = build_options(task_storage, workout_storage, grocery_storage)
        self._client: ClaudeSDKClient | None = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> ClaudeSDKClient:
        if self._client is None:
            self._client = ClaudeSDKClient(options=self._options)
            await self._client.connect()
        return self._client

    async def ask(self, text: str, session_id: str) -> str:
        async with self._lock:
            client = await self._ensure_client()
            await client.query(text, session_id=session_id)

            parts: list[str] = []
            async for message in client.receive_response():
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text:
                            parts.append(block.text)

            return "\n".join(p for p in parts if p.strip()).strip()


def build_options(
    task_storage: TaskStorage,
    workout_storage: WorkoutStorage,
    grocery_storage: GroceryStorage,
) -> ClaudeAgentOptions:
    task_server = create_task_server(task_storage)
    workout_server = create_workout_server(workout_storage)
    grocery_server = create_grocery_server(grocery_storage)
    model = os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
    return ClaudeAgentOptions(
        model=model,
        mcp_servers={
            "tasks": task_server,
            "workouts": workout_server,
            "groceries": grocery_server,
        },
        allowed_tools=[
            "mcp__tasks__add_task",
            "mcp__tasks__list_tasks",
            "mcp__tasks__complete_task",
            "mcp__tasks__delete_task",
            "mcp__tasks__get_summary",
            "mcp__tasks__schedule_reminder",
            "mcp__tasks__clear_reminders",
            "mcp__tasks__set_daily_summary",
            "mcp__workouts__log_workout",
            "mcp__workouts__edit_workout",
            "mcp__workouts__remove_exercise",
            "mcp__workouts__list_workouts",
            "mcp__workouts__workout_summary",
            "mcp__groceries__add_grocery_item",
            "mcp__groceries__list_grocery_items",
            "mcp__groceries__remove_grocery_item",
            "mcp__groceries__clear_grocery_list",
        ],
        system_prompt=SYSTEM_PROMPT,
        permission_mode="default",
    )


def chunk_text(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def strip_wake_word(text: str) -> str:
    return WAKE_WORD_RE.sub("", text, count=1).strip()


def is_reply_to_bot(message: Message, bot_id: int) -> bool:
    reply = message.reply_to_message
    if not reply or not reply.from_user:
        return False
    return reply.from_user.id == bot_id


async def daily_summary_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data if context.job else {}
    chat_id = data.get("chat_id")
    if chat_id is None:
        return

    storages: Dict[int, TaskStorage] = context.application.bot_data["storages"]
    storage = storages.get(chat_id)
    if not storage:
        return

    pending = [t for t in storage.tasks if t.get("status") == "pending"]
    high_pending = [t for t in pending if t.get("priority") == "high"]

    lines = [
        "Daily summary",
        f"Pending: {len(pending)} (High: {len(high_pending)})",
    ]

    priority_order = {"high": 0, "medium": 1, "low": 2}
    priority_labels = {"high": "HIGH", "medium": "MED", "low": "LOW"}
    for task in sorted(pending, key=lambda t: priority_order.get(t.get("priority"), 1)):
        priority = priority_labels.get(task.get("priority"), "MED")
        lines.append(f"- [{priority}] {task.get('title')}")

    await context.bot.send_message(chat_id=chat_id, text="\\n".join(lines))


def schedule_pending_reminders(
    application, chat_id: int, storage: TaskStorage
) -> None:
    reminder_jobs: Dict[tuple[int, str], object] = application.bot_data["reminder_jobs"]
    now = now_cet().replace(tzinfo=None)
    for task in storage.tasks:
        remind_at = task.get("remind_at")
        if not remind_at or task.get("reminded_at"):
            continue
        if task.get("status") == "completed":
            continue
        try:
            remind_time = datetime.fromisoformat(remind_at)
        except ValueError:
            continue
        if remind_time.tzinfo is not None:
            remind_time = remind_time.astimezone().replace(tzinfo=None)
        delay = (remind_time - now).total_seconds()
        if delay < 0:
            delay = 0

        key = (chat_id, task["id"])
        existing = reminder_jobs.get(key)
        if existing and getattr(existing, "data", {}).get("remind_at") == remind_at:
            continue
        if existing:
            existing.schedule_removal()

        job = application.job_queue.run_once(
            reminder_callback,
            when=delay,
            data={"chat_id": chat_id, "task_id": task["id"], "remind_at": remind_at},
        )
        reminder_jobs[key] = job


def schedule_daily_summary(
    application, chat_id: int, storage: TaskStorage
) -> None:
    jobs: Dict[int, object] = application.bot_data["daily_summary_jobs"]
    time_str = storage.get_daily_summary_time()

    existing = jobs.get(chat_id)
    if not time_str:
        if existing:
            existing.schedule_removal()
            jobs.pop(chat_id, None)
        return

    try:
        hour, minute = map(int, time_str.split(":"))
    except ValueError:
        return

    if existing:
        existing.schedule_removal()
        jobs.pop(chat_id, None)

    job = application.job_queue.run_daily(
        daily_summary_callback,
        time=time(hour=hour, minute=minute, tzinfo=CET_TZ),
        data={"chat_id": chat_id},
    )
    jobs[chat_id] = job


def get_chat_state(
    application, chat_id: int
) -> tuple[TaskStorage, WorkoutStorage, GroceryStorage, "ChatSession"]:
    storages: Dict[int, TaskStorage] = application.bot_data["storages"]
    workout_storages: Dict[int, WorkoutStorage] = application.bot_data[
        "workout_storages"
    ]
    grocery_storages: Dict[int, GroceryStorage] = application.bot_data[
        "grocery_storages"
    ]
    sessions: Dict[int, ChatSession] = application.bot_data["sessions"]

    storage = storages.get(chat_id)
    if storage is None:
        storage = TaskStorage(f"tasks_{chat_id}.json")
        storages[chat_id] = storage

    workout_storage = workout_storages.get(chat_id)
    if workout_storage is None:
        workout_storage = WorkoutStorage(f"workouts_{chat_id}.json")
        workout_storages[chat_id] = workout_storage

    grocery_storage = grocery_storages.get(chat_id)
    if grocery_storage is None:
        grocery_storage = GroceryStorage(f"groceries_{chat_id}.json")
        grocery_storages[chat_id] = grocery_storage

    session = sessions.get(chat_id)
    if session is None:
        session = ChatSession(storage, workout_storage, grocery_storage)
        sessions[chat_id] = session

    return storage, workout_storage, grocery_storage, session


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not message.text:
        return

    chat = update.effective_chat
    chat_id = chat.id if chat else None
    if chat_id is None:
        return

    text = message.text.strip()
    if not text:
        return

    is_private = chat.type == "private" if chat else False
    has_wake_word = bool(WAKE_WORD_RE.match(text))
    should_respond = is_private or has_wake_word or is_reply_to_bot(
        message, context.bot.id
    )
    if not should_respond:
        return

    storage, _, _, session = get_chat_state(context.application, chat_id)

    cleaned_text = strip_wake_word(text) if has_wake_word else text
    if not cleaned_text:
        return

    response = await session.ask(cleaned_text, session_id=str(chat_id))
    if not response:
        response = "Sorry, I couldn't generate a response."

    schedule_pending_reminders(context.application, chat_id, storage)
    schedule_daily_summary(context.application, chat_id, storage)

    for chunk in chunk_text(response):
        await message.reply_text(chunk)


def main() -> None:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    if os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Warning: ANTHROPIC_API_KEY is set; usage will be billed pay-as-you-go.\n"
            "Unset it to use your Claude subscription instead.\n"
        )

    async def post_init(application) -> None:
        text_filter = filters.TEXT & ~filters.COMMAND
        application.add_handler(MessageHandler(text_filter, handle_message))

    application = ApplicationBuilder().token(token).post_init(post_init).build()
    application.bot_data["sessions"] = {}
    application.bot_data["storages"] = {}
    application.bot_data["reminder_jobs"] = {}
    application.bot_data["daily_summary_jobs"] = {}
    application.bot_data["workout_storages"] = {}
    application.bot_data["grocery_storages"] = {}

    for path in Path(".").glob("tasks_*.json"):
        if not path.is_file():
            continue
        suffix = path.stem.replace("tasks_", "", 1)
        try:
            chat_id = int(suffix)
        except ValueError:
            continue
        storage = TaskStorage(str(path))
        application.bot_data["storages"][chat_id] = storage
        schedule_pending_reminders(application, chat_id, storage)
        schedule_daily_summary(application, chat_id, storage)

    for path in Path(".").glob("workouts_*.json"):
        if not path.is_file():
            continue
        suffix = path.stem.replace("workouts_", "", 1)
        try:
            chat_id = int(suffix)
        except ValueError:
            continue
        application.bot_data["workout_storages"][chat_id] = WorkoutStorage(str(path))

    for path in Path(".").glob("groceries_*.json"):
        if not path.is_file():
            continue
        suffix = path.stem.replace("groceries_", "", 1)
        try:
            chat_id = int(suffix)
        except ValueError:
            continue
        application.bot_data["grocery_storages"][chat_id] = GroceryStorage(str(path))

    print("Telegram bot running. Press Ctrl+C to stop.")
    application.run_polling()


if __name__ == "__main__":
    main()
