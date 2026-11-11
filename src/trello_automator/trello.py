from dataclasses import dataclass
from datetime import datetime, timezone

# claude.ai Trello connector (plugin), authenticated with /mcp in Claude Code
TRELLO_MCP_SERVER = "mcp__claude_ai_Trello"


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    description: str
    url: str

    @property
    def created_at(self) -> datetime:
        """Trello ids start with the creation timestamp, in hexadecimal seconds."""
        return datetime.fromtimestamp(int(self.id[:8], 16), tz=timezone.utc)

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "description": self.description, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]).strip(),
            description=str(data.get("description") or "").strip(),
            url=str(data.get("url") or ""),
        )
