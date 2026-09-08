"""
integrations/notion.py — Zero OS Notion Integration

Search pages, read databases, and create pages in Notion.
Uses a simple API token — much easier to set up than Google OAuth.

─── SETUP (one time only) ────────────────────────────────────────────
1. Go to https://www.notion.so/my-integrations
2. Click "New integration" → give it a name (e.g. "Zero OS")
3. Set capabilities: Read content, Update content, Insert content
4. Copy the "Internal Integration Token" (starts with ntn_...)
5. Add it to K:\\Astra\\.zero\\.env:
   NOTION_API_KEY=ntn_your_token_here
6. Share your Notion pages/databases with your integration:
   Open any Notion page → ··· menu → Connections → Add "Zero OS"
──────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

def _get_client() -> Any:
    """
    Return an authenticated Notion client.

    Returns:
        notion_client.Client instance.

    Raises:
        RuntimeError: If notion-client is not installed or key is missing.
    """
    try:
        from notion_client import Client
    except ImportError:
        raise RuntimeError(
            "notion-client not installed. Run:\n"
            "uv pip install notion-client"
        )

    api_key = os.getenv("NOTION_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NOTION_API_KEY not set in .env\n"
            "See setup instructions at the top of integrations/notion.py"
        )

    return Client(auth=api_key)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search(query: str, max_results: int = 10) -> list[dict[str, Any]]:
    """
    Search across all Notion pages and databases shared with Zero.

    Args:
        query: Text to search for.
        max_results: Maximum results to return.

    Returns:
        List of dicts with: id, title, type (page/database), url, last_edited.
    """
    try:
        client = _get_client()
        result = client.search(
            query=query,
            page_size=max_results,
        )
        items = []
        for obj in result.get("results", []):
            obj_type = obj.get("object", "unknown")
            # Extract title
            title = "(untitled)"
            if obj_type == "page":
                props = obj.get("properties", {})
                title_prop = props.get("title") or props.get("Name") or {}
                title_parts = title_prop.get("title", [])
                if title_parts:
                    title = "".join(p.get("plain_text", "") for p in title_parts)
            elif obj_type == "database":
                title_parts = obj.get("title", [])
                title = "".join(p.get("plain_text", "") for p in title_parts)

            items.append({
                "id": obj["id"],
                "title": title,
                "type": obj_type,
                "url": obj.get("url", ""),
                "last_edited": obj.get("last_edited_time", ""),
            })
        logger.info(f"[notion] Search '{query}' returned {len(items)} results")
        return items
    except Exception as exc:
        logger.error(f"[notion] search({query!r}) failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_page_content(page_id: str) -> str:
    """
    Read the full text content of a Notion page.

    Args:
        page_id: Notion page ID (from search results or URL).

    Returns:
        Plain text content of all blocks on the page.
    """
    try:
        client = _get_client()
        blocks = client.blocks.children.list(block_id=page_id)
        lines = []
        for block in blocks.get("results", []):
            block_type = block.get("type", "")
            content = block.get(block_type, {})
            rich_text = content.get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich_text)
            if text:
                lines.append(text)
        return "\n".join(lines)
    except Exception as exc:
        logger.error(f"[notion] get_page_content({page_id}) failed: {exc}")
        return ""


def query_database(database_id: str, filter_prop: str = "", filter_value: str = "") -> list[dict[str, Any]]:
    """
    Query a Notion database and return its rows.

    Args:
        database_id: The database ID.
        filter_prop: Optional property name to filter by (e.g. "Status").
        filter_value: Value to match for the filter.

    Returns:
        List of row dicts with property values.
    """
    try:
        client = _get_client()
        kwargs: dict[str, Any] = {"database_id": database_id}
        if filter_prop and filter_value:
            kwargs["filter"] = {
                "property": filter_prop,
                "rich_text": {"contains": filter_value},
            }
        result = client.databases.query(**kwargs)
        rows = []
        for page in result.get("results", []):
            row: dict[str, Any] = {"id": page["id"]}
            for prop_name, prop_val in page.get("properties", {}).items():
                ptype = prop_val.get("type", "")
                if ptype == "title":
                    row[prop_name] = "".join(t.get("plain_text", "") for t in prop_val.get("title", []))
                elif ptype == "rich_text":
                    row[prop_name] = "".join(t.get("plain_text", "") for t in prop_val.get("rich_text", []))
                elif ptype == "select":
                    sel = prop_val.get("select")
                    row[prop_name] = sel.get("name", "") if sel else ""
                elif ptype == "multi_select":
                    row[prop_name] = [s.get("name", "") for s in prop_val.get("multi_select", [])]
                elif ptype == "date":
                    date = prop_val.get("date")
                    row[prop_name] = date.get("start", "") if date else ""
                elif ptype == "checkbox":
                    row[prop_name] = prop_val.get("checkbox", False)
                elif ptype == "number":
                    row[prop_name] = prop_val.get("number")
                else:
                    row[prop_name] = str(prop_val.get(ptype, ""))
            rows.append(row)
        logger.info(f"[notion] Database query returned {len(rows)} rows")
        return rows
    except Exception as exc:
        logger.error(f"[notion] query_database({database_id}) failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

def create_page(
    parent_page_id: str,
    title: str,
    content: str = "",
) -> dict[str, Any]:
    """
    Create a new Notion page under a parent page.

    Args:
        parent_page_id: ID of the parent page to create under.
        title: Page title.
        content: Optional plain text content for the page body.

    Returns:
        Dict with new page id and url.
    """
    try:
        client = _get_client()
        children = []
        if content:
            # Split into paragraphs
            for para in content.split("\n"):
                if para.strip():
                    children.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": para}}]
                        },
                    })

        page = client.pages.create(
            parent={"page_id": parent_page_id},
            properties={
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}]
                }
            },
            children=children,
        )
        logger.info(f"[notion] Created page: {title}")
        return {
            "id": page["id"],
            "title": title,
            "url": page.get("url", ""),
        }
    except Exception as exc:
        logger.error(f"[notion] create_page({title!r}) failed: {exc}")
        return {"error": str(exc)}


def append_to_page(page_id: str, text: str) -> bool:
    """
    Append a paragraph block to an existing Notion page.

    Args:
        page_id: Target page ID.
        text: Text to append.

    Returns:
        True if successful.
    """
    try:
        client = _get_client()
        client.blocks.children.append(
            block_id=page_id,
            children=[{
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                },
            }],
        )
        return True
    except Exception as exc:
        logger.error(f"[notion] append_to_page({page_id}) failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------

def is_connected() -> bool:
    """Return True if Notion API key is set and valid."""
    if not os.getenv("NOTION_API_KEY"):
        return False
    try:
        client = _get_client()
        client.users.me()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI setup helper
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os as _os
    from dotenv import load_dotenv
    load_dotenv(_os.path.join(_os.path.dirname(__file__), "..", ".env"))
    print("Testing Notion integration...")
    if not os.getenv("NOTION_API_KEY"):
        print("❌ NOTION_API_KEY not set in .env")
        print("See setup instructions at the top of integrations/notion.py")
    else:
        try:
            results = search("", max_results=5)
            print(f"✅ Notion connected! Found {len(results)} shared pages/databases:")
            for r in results:
                print(f"  [{r['type']}] {r['title']} — {r['url']}")
        except Exception as exc:
            print(f"❌ Error: {exc}")
