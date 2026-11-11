"""Rules that decide which cards are offered and which one is implemented."""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from trello_automator.trello import Card

THURSDAY = 3
# Outside Thursday, the Squeaker group and the automatic choice only get cards up to this level
MAX_REGULAR_COMPLEXITY = 7
MAX_BRANCH_SLUG_LENGTH = 50


@dataclass(frozen=True)
class RatedCard:
    card: Card
    complexity: int


def is_all_levels_session(now: datetime) -> bool:
    """Thursday sessions accept every complexity level."""
    return now.weekday() == THURSDAY


def filter_eligible(rated_cards: list[RatedCard], all_levels: bool) -> list[RatedCard]:
    if all_levels:
        return list(rated_cards)
    return [
        rated_card
        for rated_card in rated_cards
        if rated_card.complexity <= MAX_REGULAR_COMPLEXITY
    ]


def choose_automatically(eligible_cards: list[RatedCard], all_levels: bool) -> RatedCard:
    """Most recent card; on Thursdays the most complex one (most recent on a tie)."""
    if all_levels:
        return max(
            eligible_cards,
            key=lambda rated_card: (rated_card.complexity, rated_card.card.created_at),
        )
    return max(eligible_cards, key=lambda rated_card: rated_card.card.created_at)


def parse_card_number(reply_text: Optional[str], card_count: int) -> Optional[int]:
    """1-based card number of a reply made only of a number in range, None otherwise."""
    match = re.fullmatch(r"\s*(\d+)\s*", reply_text or "")
    if match is None:
        return None
    card_number = int(match.group(1))
    return card_number if 1 <= card_number <= card_count else None


def is_confirmation(reply_text: Optional[str]) -> bool:
    return (reply_text or "").strip().lower().rstrip(".!") in ("sim", "s")


def build_branch_slug(card_name: str) -> str:
    without_accents = (
        unicodedata.normalize("NFKD", card_name).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", without_accents.lower()).strip("-")
    return slug[:MAX_BRANCH_SLUG_LENGTH].rstrip("-") or "task"
