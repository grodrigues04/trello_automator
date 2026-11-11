import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DATA_DIR = PROJECT_ROOT / "data"
SOURCE = "trello_automator"

# Never passed to the Claude processes: they read card descriptions written by other people
SECRET_VARIABLES = ("TRELLO_API_KEY", "TRELLO_TOKEN", "MONGO_URI", "ENCRYPTION_PASSWORD")


@dataclass(frozen=True)
class Settings:
    trello_api_key: str
    trello_token: str
    trello_board_name: str
    trello_list_name: str
    mongo_uri: str
    encryption_password: str
    squeaker_group: str
    repo_path: Path
    github_repo: str
    evaluation_model: str
    implementation_model: str
    implementation_timeout_minutes: int
    implementation_max_turns: int


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        trello_api_key=os.environ["TRELLO_API_KEY"],
        trello_token=os.environ["TRELLO_TOKEN"],
        trello_board_name=os.environ.get("TRELLO_BOARD_NAME", "Squeaker"),
        trello_list_name=os.environ.get("TRELLO_LIST_NAME", "GUSTAVO"),
        mongo_uri=os.environ["MONGO_URI"],
        encryption_password=os.environ["ENCRYPTION_PASSWORD"],
        squeaker_group=os.environ["SQUEAKER_GROUP"],
        repo_path=Path(os.environ.get("REPO_PATH", "/home/vip-2002/MyProjects/ratUFSC")),
        github_repo=os.environ.get("GITHUB_REPO", "matheusfaustinott/ratUFSC"),
        evaluation_model=os.environ.get("EVALUATION_MODEL", "claude-sonnet-5-5"),
        implementation_model=os.environ.get("IMPLEMENTATION_MODEL", "claude-opus-5-5"),
        implementation_timeout_minutes=int(os.environ.get("IMPLEMENTATION_TIMEOUT_MINUTES", "240")),
        implementation_max_turns=int(os.environ.get("IMPLEMENTATION_MAX_TURNS", "400")),
    )


def build_claude_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in SECRET_VARIABLES}
