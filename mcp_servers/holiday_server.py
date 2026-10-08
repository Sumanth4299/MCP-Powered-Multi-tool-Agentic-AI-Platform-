"""
FastMCP Indian Government Holiday Server.
Inspects local curated holiday dataset for 2026 scheduling validation.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP, Context  # type: ignore[attr-defined]
except (ImportError, AttributeError):
    from fastmcp import FastMCP, Context  # type: ignore[no-redef]

mcp = FastMCP(
    name="Holiday Checker Server",
    instructions="Inspects gazetted and state public holidays for India in 2026.",
)

DATA_PATH = Path(__file__).parent.parent / "data" / "holidays.json"


def _load_holidays() -> list[dict[str, Any]]:
    if not DATA_PATH.exists():
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@mcp.tool(
    name="check_holidays",
    description="Check if a specific date or date range contains Indian national or regional government holidays.",
)
async def check_holidays(
    date: str,
    region: str | None = "India",
    ctx: Any = None,
) -> str:
    """
    Args:
        date: Target date formatted as 'YYYY-MM-DD' (e.g., '2026-10-02').
        region: Geographic scope to include ('India', 'Telangana', etc.).
    """
    try:
        query_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()
    except ValueError:
        return json.dumps({"error": f"Invalid date format: '{date}'. Use YYYY-MM-DD."})

    holidays = _load_holidays()
    target_region = (region or "India").lower()

    matches = []
    for h in holidays:
        h_date = datetime.strptime(h["date"], "%Y-%m-%d").date()
        h_region = h.get("region", "India").lower()

        if h_date == query_date:
            if target_region == "all" or h_region in ["india", target_region]:
                matches.append(h)

    if not matches:
        return json.dumps({
            "is_holiday": False,
            "date": date,
            "region": region,
            "message": f"No official public holidays detected on {date} for {region}."
        })

    return json.dumps({
        "is_holiday": True,
        "date": date,
        "holidays": matches,
        "message": f"Detected {len(matches)} official holiday(s) on {date}: {', '.join([m['name'] for m in matches])}."
    }, indent=2)


if __name__ == "__main__":
    mcp.run()