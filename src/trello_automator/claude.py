"""The Claude sessions of the routine.

Each session gets only the tools it needs:
- reading the cards and marking one as complete: only the Trello plugin tools;
- complexity: Read/Grep/Glob in the repository;
- risk review: no tools at all, so the content under review cannot make it run anything;
- implementation and corrections: everything inside the repository, but no MCP connector
  (--strict-mcp-config), so a malicious card cannot reach Trello, Gmail, Drive...
"""

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template

from trello_automator.config import PROMPTS_DIR, Settings, build_claude_environment
from trello_automator.pull_request import Feedback, TrackedPullRequest
from trello_automator.trello import TRELLO_MCP_SERVER, Card

log = logging.getLogger(__name__)

EVALUATION_TIMEOUT_SECONDS = 15 * 60
EVALUATION_MAX_TURNS = 40
# The Trello connector has write tools too: everything that is not reading is denied
TRELLO_WRITE_TOOL_WORDS = ("add", "create", "update", "move", "delete", "archive", "set", "remove")

CARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "pattern": "^[0-9a-f]{24}$"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                    "complete": {"type": "boolean"},
                },
                "required": ["id", "name", "description", "url", "complete"],
            },
        }
    },
    "required": ["cards"],
}

COMPLEXITY_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "complexity": {"type": "integer", "minimum": 0, "maximum": 10},
                },
                "required": ["id", "complexity"],
            },
        }
    },
    "required": ["cards"],
}

RISK_SCHEMA = {
    "type": "object",
    "properties": {"risky": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["risky", "reason"],
}

COMPLETE_SCHEMA = {
    "type": "object",
    "properties": {"complete": {"type": "boolean"}, "error": {"type": "string"}},
    "required": ["complete"],
}


class ClaudeError(Exception):
    pass


@dataclass(frozen=True)
class RiskReview:
    risky: bool
    reason: str


def read_prompt(file_name: str, **values: str) -> str:
    template = Template((PROMPTS_DIR / file_name).read_text(encoding="utf-8"))
    return template.safe_substitute(values)


def serialize_cards(cards: list[Card]) -> str:
    return json.dumps(
        [{"id": card.id, "name": card.name, "description": card.description} for card in cards],
        ensure_ascii=False,
        indent=2,
    )


def list_trello_tools() -> list[str]:
    """Names of the Trello plugin tools, read from a session that only lists them."""
    output = run_structured(
        prompt=(
            f"List the exact names of every tool you have that starts with {TRELLO_MCP_SERVER}__. "
            "Do not call any tool."
        ),
        schema={
            "type": "object",
            "properties": {"tools": {"type": "array", "items": {"type": "string"}}},
            "required": ["tools"],
        },
        model="claude-haiku-5-5",
        cwd=PROMPTS_DIR,
        # Nothing is allowed, so a tool call would be denied: the tools are only listed
        arguments=["--tools", ""],
        max_turns=2,
    )
    tools = [tool for tool in output["tools"] if tool.startswith(f"{TRELLO_MCP_SERVER}__")]
    if not tools:
        raise ClaudeError('o plugin "claude.ai Trello" não está autenticado: rode /mcp no Claude Code')
    return tools


def split_trello_tools() -> tuple[list[str], list[str]]:
    """(reading tools, writing tools) of the Trello plugin."""
    read_tools, write_tools = [], []
    for tool in list_trello_tools():
        action = tool.removeprefix(f"{TRELLO_MCP_SERVER}__").lower()
        is_write = any(word in action for word in TRELLO_WRITE_TOOL_WORDS)
        (write_tools if is_write else read_tools).append(tool)
    return read_tools, write_tools


def run_structured(
    prompt: str, schema: dict, model: str, cwd: Path, arguments: list[str], max_turns: int
) -> dict:
    """Runs `claude -p` and returns the JSON that matches `schema`."""
    try:
        completed = subprocess.run(
            [
                "claude",
                "-p",
                "--model",
                model,
                "--max-turns",
                str(max_turns),
                "--no-session-persistence",
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(schema),
                *arguments,
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=build_claude_environment(),
            timeout=EVALUATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise ClaudeError(f"o Claude passou de {EVALUATION_TIMEOUT_SECONDS // 60} minutos") from error
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ClaudeError(
            f"saída inválida do Claude (código {completed.returncode}): {completed.stderr[-500:]}"
        ) from error
    if result.get("is_error") or not isinstance(result.get("structured_output"), dict):
        raise ClaudeError(f"o Claude não devolveu o JSON esperado: {str(result)[-500:]}")
    return result["structured_output"]


def read_cards(settings: Settings) -> list[Card]:
    """Open cards of the list that are not marked as complete, in board order."""
    read_tools, write_tools = split_trello_tools()
    output = run_structured(
        prompt=read_prompt(
            "read_cards.md",
            board_name=settings.trello_board_name,
            list_name=settings.trello_list_name,
        ),
        schema=CARDS_SCHEMA,
        model=settings.evaluation_model,
        cwd=PROMPTS_DIR,
        arguments=[
            "--tools", "",
            "--allowedTools", *read_tools,
            "--disallowedTools", *write_tools,
        ],
        max_turns=EVALUATION_MAX_TURNS,
    )
    return [Card.from_dict(card) for card in output["cards"] if not card["complete"]]


def mark_card_complete(card: Card, settings: Settings) -> None:
    _, write_tools = split_trello_tools()
    output = run_structured(
        prompt=read_prompt("mark_complete.md", card_id=card.id, card_name=card.name),
        schema=COMPLETE_SCHEMA,
        model=settings.evaluation_model,
        cwd=PROMPTS_DIR,
        arguments=["--tools", "", "--allowedTools", TRELLO_MCP_SERVER],
        max_turns=EVALUATION_MAX_TURNS,
    )
    if not output["complete"]:
        raise ClaudeError(f"não foi possível marcar o card como concluído: {output.get('error')}")
    log.info(f"Card {card.id} marked as complete (write tools available: {write_tools})")


def evaluate_complexity(cards: list[Card], settings: Settings) -> dict[str, int]:
    """Complexity of each card id. Cards Claude left out are rated 10 (offered only on Thursdays)."""
    output = run_structured(
        prompt=read_prompt("complexity.md") + serialize_cards(cards),
        schema=COMPLEXITY_SCHEMA,
        model=settings.evaluation_model,
        cwd=settings.repo_path,
        arguments=["--strict-mcp-config", "--tools", "Read,Grep,Glob"],
        max_turns=EVALUATION_MAX_TURNS,
    )
    complexities = {
        rated_card["id"]: max(0, min(10, int(rated_card["complexity"])))
        for rated_card in output["cards"]
    }
    for card in cards:
        if card.id not in complexities:
            log.warning(f"Claude did not rate card {card.id}, using complexity 10")
            complexities[card.id] = 10
    return complexities


def review_risk(content: dict, settings: Settings) -> RiskReview:
    """Reviews a card or PR comments without any tool.

    A review that fails (ex.: refused by Claude's own safety filter) counts as risky.
    """
    try:
        output = run_structured(
            prompt=read_prompt("risk_review.md")
            + json.dumps(content, ensure_ascii=False, indent=2),
            schema=RISK_SCHEMA,
            model=settings.evaluation_model,
            cwd=PROMPTS_DIR,
            arguments=["--strict-mcp-config", "--tools", ""],
            max_turns=2,
        )
    except ClaudeError as error:
        log.warning(f"Risk review failed, treating the content as risky: {error}")
        return RiskReview(
            risky=True,
            reason=(
                "a revisão de risco não conseguiu avaliar o conteúdo (o filtro de segurança do "
                "Claude costuma recusar pedidos perigosos). Detalhes no log da rotina."
            ),
        )
    return RiskReview(risky=bool(output["risky"]), reason=str(output["reason"]).strip())


def run_free_session(prompt: str, log_path: Path, settings: Settings) -> int:
    """Runs Claude without permission prompts in the repository. Returns the exit code."""
    with log_path.open("a", encoding="utf-8") as log_file:
        try:
            completed = subprocess.run(
                [
                    "claude",
                    "-p",
                    "--model",
                    settings.implementation_model,
                    "--max-turns",
                    str(settings.implementation_max_turns),
                    "--permission-mode",
                    "bypassPermissions",
                    "--strict-mcp-config",
                ],
                input=prompt,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=settings.repo_path,
                env=build_claude_environment(),
                timeout=settings.implementation_timeout_minutes * 60,
            )
        except subprocess.TimeoutExpired:
            return 124
    return completed.returncode


def implement(
    card: Card,
    branch_slug: str,
    repository_state: str,
    report_path: Path,
    log_path: Path,
    settings: Settings,
) -> int:
    prompt = read_prompt(
        "implementation.md",
        card_name=card.name,
        card_url=card.url,
        card_description=card.description,
        repository_state=repository_state,
        branch_slug=branch_slug,
        github_repo=settings.github_repo,
        report_path=str(report_path),
    )
    return run_free_session(prompt, log_path, settings)


def apply_corrections(
    tracked: TrackedPullRequest,
    feedback: list[Feedback],
    report_path: Path,
    log_path: Path,
    settings: Settings,
) -> int:
    prompt = read_prompt(
        "correction.md",
        card_name=tracked.card.name,
        card_url=tracked.card.url,
        card_description=tracked.card.description,
        pr_url=tracked.url,
        branch=tracked.branch,
        feedback="\n\n".join(item.format() for item in feedback),
        report_path=str(report_path),
    )
    return run_free_session(prompt, log_path, settings)
