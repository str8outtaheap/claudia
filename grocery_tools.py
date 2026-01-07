"""MCP tools for grocery list management."""

import json

from claude_agent_sdk import tool, create_sdk_mcp_server
from grocery_storage import GroceryStorage


def _json_response(payload: dict, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    if is_error:
        result["is_error"] = True
    return result


def _schema(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": []}


def create_grocery_server(storage: GroceryStorage):
    """Create MCP server with grocery list tools bound to a storage instance."""

    @tool(
        "add_grocery_item",
        "Add item(s) to the grocery list.",
        _schema(
            {
                "item": {"type": "string"},
                "name": {"type": "string"},
                "quantity": {"type": "string"},
                "unit": {"type": "string"},
                "items": {"type": "array"},
            }
        ),
    )
    async def add_grocery_item(args: dict) -> dict:
        items_arg = args.get("items")
        created: list[dict] = []

        def add_one(entry: dict) -> None:
            name = (entry.get("name") or entry.get("item") or "").strip()
            if not name:
                return
            quantity = entry.get("quantity")
            unit = entry.get("unit")
            created.append(storage.add_item(name, quantity, unit))

        if isinstance(items_arg, list):
            for entry in items_arg:
                if isinstance(entry, str):
                    add_one({"name": entry})
                elif isinstance(entry, dict):
                    add_one(entry)
        else:
            add_one(args)

        if not created:
            return _json_response(
                {"ok": False, "error": "item name is required"}, is_error=True
            )

        return _json_response({"ok": True, "items": created})

    @tool(
        "list_grocery_items",
        "List all grocery items.",
        _schema({}),
    )
    async def list_grocery_items(args: dict) -> dict:
        items = storage.list_items()
        return _json_response({"ok": True, "items": items})

    @tool(
        "remove_grocery_item",
        "Remove an item by id or name.",
        _schema({"id": {"type": "string"}, "item": {"type": "string"}, "name": {"type": "string"}}),
    )
    async def remove_grocery_item(args: dict) -> dict:
        item_id = (args.get("id") or "").strip() or None
        name = (args.get("name") or args.get("item") or "").strip() or None
        removed = storage.remove_item(item_id=item_id, name=name)
        if not removed:
            return _json_response(
                {"ok": False, "error": "item not found"}, is_error=True
            )
        return _json_response({"ok": True, "removed": removed})

    @tool(
        "clear_grocery_list",
        "Clear all grocery items.",
        _schema({}),
    )
    async def clear_grocery_list(args: dict) -> dict:
        cleared = storage.clear()
        return _json_response({"ok": True, "cleared": cleared})

    return create_sdk_mcp_server(
        name="grocery-list",
        version="1.0.0",
        tools=[add_grocery_item, list_grocery_items, remove_grocery_item, clear_grocery_list],
    )
