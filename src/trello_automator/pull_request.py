"""The pull request opened by the routine, and the review feedback it received.

Only one card is worked on at a time: while the routine's PR is open, sessions only apply its
review feedback. The PR is stored in data/pull_request.json from its opening until it is merged
(card marked as complete in Trello) or closed without merge.
"""

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from trello_automator.trello import Card

# Only people with access to the repository count as reviewers
REVIEWER_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")


class PullRequestState(str, Enum):
    OPEN = "OPEN"
    MERGED = "MERGED"
    CLOSED = "CLOSED"


@dataclass
class TrackedPullRequest:
    card: Card
    complexity: int
    branch: str
    number: int
    url: str
    # Feedback created after this moment was not handled yet
    handled_until: str

    def to_dict(self) -> dict:
        return {**asdict(self), "card": self.card.to_dict()}

    @classmethod
    def from_dict(cls, data: dict) -> "TrackedPullRequest":
        return cls(**{**data, "card": Card.from_dict(data["card"])})


@dataclass(frozen=True)
class Feedback:
    author: str
    kind: str
    body: str
    created_at: str
    location: str = ""

    def format(self) -> str:
        location = f" em `{self.location}`" if self.location else ""
        return f"- {self.kind} de @{self.author}{location} ({self.created_at}):\n{self.body}"


def load_tracked(state_path: Path) -> Optional[TrackedPullRequest]:
    if not state_path.exists():
        return None
    return TrackedPullRequest.from_dict(json.loads(state_path.read_text(encoding="utf-8")))


def save_tracked(state_path: Path, tracked: TrackedPullRequest) -> None:
    state_path.write_text(
        json.dumps(tracked.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_gh(*arguments: str) -> str:
    completed = subprocess.run(
        ["gh", *arguments], capture_output=True, text=True, timeout=120, check=True
    )
    return completed.stdout


def view_pull_request(github_repo: str, branch_or_number: str) -> Optional[dict]:
    """number, url, state and headRefName of the PR, None when it does not exist."""
    try:
        output = run_gh(
            "pr", "view", branch_or_number, "--repo", github_repo,
            "--json", "number,url,state,headRefName",
        )
    except subprocess.CalledProcessError:
        return None
    return json.loads(output)


def is_after(created_at: str, handled_until: str) -> bool:
    return datetime.fromisoformat(created_at.replace("Z", "+00:00")) > datetime.fromisoformat(
        handled_until
    )


def parse_feedback(
    issue_comments: list[dict], review_comments: list[dict], reviews: list[dict], handled_until: str
) -> list[Feedback]:
    feedback = []
    for comment in issue_comments:
        feedback.append(
            (comment, Feedback(comment["user"]["login"], "Comentário", comment["body"],
                               comment["created_at"]))
        )
    for comment in review_comments:
        location = f"{comment['path']}:{comment.get('line') or comment.get('original_line') or ''}"
        feedback.append(
            (comment, Feedback(comment["user"]["login"], "Comentário de review", comment["body"],
                               comment["created_at"], location.rstrip(":")))
        )
    for review in reviews:
        # Approvals and empty reviews carry nothing to apply; their inline comments come above
        if not (review.get("body") or "").strip() or review.get("submitted_at") is None:
            continue
        feedback.append(
            (review, Feedback(review["user"]["login"], f"Review ({review['state']})",
                              review["body"], review["submitted_at"]))
        )
    return sorted(
        (
            item
            for source, item in feedback
            if source.get("author_association") in REVIEWER_ASSOCIATIONS
            and item.body.strip()
            and is_after(item.created_at, handled_until)
        ),
        key=lambda item: item.created_at,
    )


def fetch_new_feedback(github_repo: str, tracked: TrackedPullRequest) -> list[Feedback]:
    def fetch(path: str) -> list[dict]:
        pages = json.loads(run_gh("api", "--paginate", "--slurp", path))
        return [item for page in pages for item in page]

    base_path = f"repos/{github_repo}"
    return parse_feedback(
        issue_comments=fetch(f"{base_path}/issues/{tracked.number}/comments"),
        review_comments=fetch(f"{base_path}/pulls/{tracked.number}/comments"),
        reviews=fetch(f"{base_path}/pulls/{tracked.number}/reviews"),
        handled_until=tracked.handled_until,
    )
