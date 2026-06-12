"""Betting round state machine for poker-style games.

Tracks contributions, acted status, and determines when a betting round
completes (all active non-all-in players have acted and contributions
equal the current bet).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BettingRoundState:
    """Mutable state for a single betting round.

    Attributes:
        current_bet: The current bet level that active players must match.
        contributions: Per-player chip contributions in this betting round.
        active_players: Players who have not folded (still in the hand).
        acted: Players who have acted since the last raise.
        all_in_players: Players who have gone all-in.
        last_raiser: The player who made the last raise (None if no raise yet).
    """

    current_bet: int = 0
    contributions: dict[str, int] = field(default_factory=dict)
    active_players: list[str] = field(default_factory=list)
    acted: set[str] = field(default_factory=set)
    all_in_players: set[str] = field(default_factory=set)
    last_raiser: str | None = None

    def init_round(self, players: list[str]) -> None:
        """Initialize a new betting round for the given players."""
        self.current_bet = 0
        self.contributions = {p: 0 for p in players}
        self.active_players = list(players)
        self.acted = set()
        self.all_in_players = set()
        self.last_raiser = None

    def players_who_must_act(self) -> list[str]:
        """Players who still need to act before the round can end."""
        return [
            p for p in self.active_players
            if p not in self.acted and p not in self.all_in_players
        ]

    def is_round_complete(self) -> bool:
        """Whether the betting round is complete.

        Complete when all active (non-folded, non-all-in) players have acted
        AND all their contributions equal the current bet (or they are all-in).
        """
        for p in self.active_players:
            if p in self.all_in_players:
                continue
            if p not in self.acted:
                return False
            if self.contributions.get(p, 0) != self.current_bet:
                return False
        return True

    def player_contribution(self, player: str) -> int:
        """How much a player has contributed this round."""
        return self.contributions.get(player, 0)

    def remaining_active_count(self) -> int:
        """Number of non-folded players."""
        return len(self.active_players)
