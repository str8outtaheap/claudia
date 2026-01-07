# Claudia

Tiny Telegram daily assistant powered by the Claude Agent SDK.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file (see `.env.example`).

## Run
```bash
python3 claudia.py
```

## Features
- Natural chat via Telegram (private: responds to all messages; groups: requires “Claudia” or a reply)
- Task management: add, list, complete, delete, summary
- Priorities with `[LOW]/[MED]/[HIGH]` formatting
- Reminders (e.g., “Claudia remind me in 5 minutes”, “Claudia remind me tomorrow”)
- Daily summaries in CET (e.g., “Claudia daily summary at 08:00”)
- Workout logging (sets/reps/weight, default unit: kg). Includes progress summaries (weight/%), list output with weights/reps, and edit/remove for logged exercises.
- Grocery list management (add, list, remove, clear)
- Per‑chat storage (`tasks_<chat_id>.json`, `settings_<chat_id>.json`, `workouts_<chat_id>.json`, `groceries_<chat_id>.json`)

## Notes
- Set `ANTHROPIC_API_KEY` to use API billing; otherwise it uses your Claude subscription.
