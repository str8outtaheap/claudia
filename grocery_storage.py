"""Grocery list storage using JSON file persistence."""

import json
from datetime import datetime
from pathlib import Path
import uuid


class GroceryStorage:
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        if self.file_path.exists():
            with open(self.file_path, "r") as f:
                self.items = json.load(f)
        else:
            self.items = []

    def save(self) -> None:
        with open(self.file_path, "w") as f:
            json.dump(self.items, f, indent=2)

    def add_item(self, name: str, quantity: str | None = None, unit: str | None = None) -> dict:
        item = {
            "id": str(uuid.uuid4())[:8],
            "name": name,
            "quantity": quantity,
            "unit": unit,
            "created_at": datetime.now().isoformat(),
        }
        self.items.append(item)
        self.save()
        return item

    def list_items(self) -> list[dict]:
        return self.items

    def remove_item(self, item_id: str | None = None, name: str | None = None) -> dict | None:
        if item_id:
            for i, item in enumerate(self.items):
                if item["id"] == item_id:
                    removed = self.items.pop(i)
                    self.save()
                    return removed
            return None

        if name:
            needle = name.strip().lower()
            for i in range(len(self.items) - 1, -1, -1):
                if (self.items[i].get("name") or "").strip().lower() == needle:
                    removed = self.items.pop(i)
                    self.save()
                    return removed
        return None

    def clear(self) -> int:
        count = len(self.items)
        self.items = []
        if count:
            self.save()
        return count
