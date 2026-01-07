"""Workout storage using JSON file persistence."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional
import uuid


class WorkoutStorage:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.workouts: list[dict] = []
        self.load()

    def load(self) -> None:
        if self.file_path.exists():
            with open(self.file_path, "r") as f:
                self.workouts = json.load(f)
        else:
            self.workouts = []

    def save(self) -> None:
        with open(self.file_path, "w") as f:
            json.dump(self.workouts, f, indent=2)

    def add_workout(
        self,
        date: str,
        exercises: list[dict],
        notes: str | None = None,
    ) -> dict:
        workout = {
            "id": str(uuid.uuid4())[:8],
            "date": date,
            "type": "strength",
            "exercises": exercises,
            "notes": notes or "",
            "created_at": datetime.now().isoformat(),
        }
        self.workouts.append(workout)
        self.save()
        return workout

    def list_workouts(self, date_from: str | None, date_to: str | None) -> list[dict]:
        if not date_from and not date_to:
            return self.workouts

        def in_range(date_str: str) -> bool:
            if date_from and date_str < date_from:
                return False
            if date_to and date_str > date_to:
                return False
            return True

        return [w for w in self.workouts if in_range(w["date"])]

    def update_exercise(
        self, exercise: str, sets: list, date: str | None = None, notes: str | None = None
    ) -> dict | None:
        target = None
        exercise_key = exercise.strip().lower()
        for workout in reversed(self.workouts):
            if date and workout.get("date") != date:
                continue
            for entry in workout.get("exercises", []):
                name = (entry.get("name") or "").strip().lower()
                if name == exercise_key:
                    target = (workout, entry)
                    break
            if target:
                break

        if not target:
            return None

        workout, entry = target
        entry["sets"] = sets
        if notes is not None:
            workout["notes"] = notes
        self.save()
        return {
            "date": workout.get("date"),
            "exercise": entry.get("name") or exercise,
            "sets": entry.get("sets") or [],
        }

    def remove_exercise(self, exercise: str, date: str | None = None) -> dict | None:
        exercise_key = exercise.strip().lower()
        for idx in range(len(self.workouts) - 1, -1, -1):
            workout = self.workouts[idx]
            if date and workout.get("date") != date:
                continue
            exercises = workout.get("exercises", [])
            for ex_idx in range(len(exercises) - 1, -1, -1):
                entry = exercises[ex_idx]
                name = (entry.get("name") or "").strip().lower()
                if name != exercise_key:
                    continue
                removed = exercises.pop(ex_idx)
                if not exercises:
                    self.workouts.pop(idx)
                self.save()
                return {
                    "date": workout.get("date"),
                    "exercise": removed.get("name") or exercise,
                }
        return None
