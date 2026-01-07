"""MCP tools for workout logging."""

import json
from datetime import timedelta

from claude_agent_sdk import tool, create_sdk_mcp_server
from datetime_utils import now_cet, today_cet, normalize_date
from workout_storage import WorkoutStorage


def _json_response(payload: dict, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    if is_error:
        result["is_error"] = True
    return result

def create_workout_server(storage: WorkoutStorage):
    """Create MCP server with workout logging tools bound to a storage instance."""

    @tool(
        "log_workout",
        "Log a strength workout with exercises and sets.",
        {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "exercises": {"type": "array"},
                "exercise": {"type": "string"},
                "name": {"type": "string"},
                "sets": {"type": "array"},
                "notes": {"type": "string"},
            },
            "required": [],
        },
    )
    async def log_workout(args: dict) -> dict:
        date = normalize_date(args.get("date")) or today_cet()
        exercises = args.get("exercises")
        if exercises is None:
            single_name = (args.get("exercise") or args.get("name") or "").strip()
            if single_name:
                exercises = [{"name": single_name, "sets": args.get("sets") or []}]
            else:
                exercises = []
        if isinstance(exercises, dict):
            exercises = [exercises]
        if not isinstance(exercises, list):
            exercises = []
        notes = args.get("notes") or ""

        cleaned_exercises: list[dict] = []
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            name = (exercise.get("name") or exercise.get("exercise") or "").strip()
            if not name:
                continue
            sets = exercise.get("sets") or []
            if isinstance(sets, dict):
                sets = [sets]
            if not isinstance(sets, list):
                sets = []
            cleaned_sets: list[dict] = []
            for entry in sets:
                if not isinstance(entry, dict):
                    continue
                cleaned_sets.append(
                    {
                        "reps": entry.get("reps"),
                        "weight": entry.get("weight"),
                        "unit": entry.get("unit") or "kg",
                    }
                )
            cleaned_exercises.append({"name": name, "sets": cleaned_sets})

        if not cleaned_exercises:
            return _json_response(
                {"ok": False, "error": "exercises with sets are required"},
                is_error=True,
            )

        workout = storage.add_workout(date, cleaned_exercises, notes)
        return _json_response({"ok": True, "workout": workout})

    @tool(
        "edit_workout",
        "Edit a logged exercise by name (optionally date) and replace its sets.",
        {
            "type": "object",
            "properties": {
                "exercise": {"type": "string"},
                "name": {"type": "string"},
                "date": {"type": "string"},
                "sets": {"type": "array"},
                "notes": {"type": "string"},
            },
            "required": [],
        },
    )
    async def edit_workout(args: dict) -> dict:
        exercise = (args.get("exercise") or args.get("name") or "").strip()
        if not exercise:
            return _json_response(
                {"ok": False, "error": "exercise name is required"},
                is_error=True,
            )

        sets = args.get("sets")
        if sets is None:
            return _json_response(
                {"ok": False, "error": "sets are required to update"},
                is_error=True,
            )
        if isinstance(sets, dict):
            sets = [sets]
        if not isinstance(sets, list):
            sets = []

        date = _parse_date(args.get("date"))
        notes = args.get("notes")

        updated = storage.update_exercise(exercise, sets, date=date, notes=notes)
        if not updated:
            return _json_response(
                {"ok": False, "error": "No matching exercise found"}, is_error=True
            )

        return _json_response({"ok": True, "updated": updated})

    @tool(
        "remove_exercise",
        "Remove a logged exercise by name (optionally date).",
        {
            "type": "object",
            "properties": {
                "exercise": {"type": "string"},
                "name": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": [],
        },
    )
    async def remove_exercise(args: dict) -> dict:
        exercise = (args.get("exercise") or args.get("name") or "").strip()
        if not exercise:
            return _json_response(
                {"ok": False, "error": "exercise name is required"},
                is_error=True,
            )

        date = _parse_date(args.get("date"))
        removed = storage.remove_exercise(exercise, date=date)
        if not removed:
            return _json_response(
                {"ok": False, "error": "No matching exercise found"}, is_error=True
            )

        return _json_response({"ok": True, "removed": removed})

    @tool(
        "list_workouts",
        "List workouts in a date range (YYYY-MM-DD).",
        {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
            },
            "required": [],
        },
    )
    async def list_workouts(args: dict) -> dict:
        date_from = normalize_date(args.get("date_from"))
        date_to = normalize_date(args.get("date_to"))

        if not date_from and not date_to:
            date_to = today_cet()
            date_from = (now_cet().date() - timedelta(days=6)).isoformat()

        workouts = storage.list_workouts(date_from, date_to)
        return _json_response(
            {"ok": True, "date_from": date_from, "date_to": date_to, "workouts": workouts}
        )

    @tool(
        "workout_summary",
        "Summarize workout progress in a date range (YYYY-MM-DD).",
        {
            "type": "object",
            "properties": {
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "exercise": {"type": "string"},
            },
            "required": [],
        },
    )
    async def workout_summary(args: dict) -> dict:
        date_from = normalize_date(args.get("date_from"))
        date_to = normalize_date(args.get("date_to"))
        exercise_filter = (args.get("exercise") or "").strip().lower()
        exercise_names = {
            name.strip().lower()
            for name in exercise_filter.split(",")
            if name.strip()
        }

        workouts = storage.list_workouts(date_from, date_to)
        if not workouts:
            return _json_response(
                {"ok": True, "progress": [], "date_from": date_from, "date_to": date_to}
            )

        stats: dict[str, dict] = {}
        for workout in workouts:
            workout_date = workout["date"]
            for exercise in workout.get("exercises", []):
                name = (exercise.get("name") or "").strip()
                if not name:
                    continue
                normalized = name.lower()
                if exercise_names and normalized not in exercise_names:
                    continue
                sets = exercise.get("sets") or []
                if not sets:
                    continue
                max_weight = 0.0
                max_unit = "kg"
                for s in sets:
                    if not isinstance(s, dict):
                        continue
                    weight = s.get("weight")
                    try:
                        weight_value = float(weight)
                    except Exception:
                        continue
                    if weight_value > max_weight:
                        max_weight = weight_value
                        max_unit = s.get("unit") or "kg"
                if max_weight <= 0:
                    continue
                entry = stats.setdefault(
                    normalized,
                    {
                        "name": name,
                        "first_date": "",
                        "first_weight": 0.0,
                        "first_unit": "kg",
                        "last_date": "",
                        "last_weight": 0.0,
                        "last_unit": "kg",
                    },
                )
                if not entry["first_date"] or workout_date < entry["first_date"]:
                    entry["first_date"] = workout_date
                    entry["first_weight"] = max_weight
                    entry["first_unit"] = max_unit
                elif (
                    workout_date == entry["first_date"]
                    and max_weight > entry["first_weight"]
                ):
                    entry["first_weight"] = max_weight
                    entry["first_unit"] = max_unit
                if not entry["last_date"] or workout_date > entry["last_date"]:
                    entry["last_date"] = workout_date
                    entry["last_weight"] = max_weight
                    entry["last_unit"] = max_unit
                elif (
                    workout_date == entry["last_date"]
                    and max_weight > entry["last_weight"]
                ):
                    entry["last_weight"] = max_weight
                    entry["last_unit"] = max_unit

        progress = []
        for entry in sorted(stats.values(), key=lambda e: e["name"].lower()):
            first_weight = entry["first_weight"]
            last_weight = entry["last_weight"]
            first_unit = entry["first_unit"]
            last_unit = entry["last_unit"]
            delta = last_weight - first_weight
            pct = None
            if first_weight > 0 and first_unit == last_unit:
                pct = (delta / first_weight) * 100
            progress.append(
                {
                    "exercise": entry["name"],
                    "first_date": entry["first_date"],
                    "first_weight": first_weight,
                    "first_unit": first_unit,
                    "last_date": entry["last_date"],
                    "last_weight": last_weight,
                    "last_unit": last_unit,
                    "delta": delta,
                    "pct": pct,
                }
            )

        return _json_response(
            {
                "ok": True,
                "date_from": date_from,
                "date_to": date_to,
                "progress": progress,
            }
        )

    return create_sdk_mcp_server(
        name="workout-logger",
        version="1.0.0",
        tools=[log_workout, edit_workout, remove_exercise, list_workouts, workout_summary],
    )
