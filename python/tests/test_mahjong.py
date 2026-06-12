"""Tests for Mahjong (Riichi simplified): 4 players, 136 tiles, draw-and-discard.

Exercises: wall management, 13-tile hands, draw/discard flow, interrupt
claims (chi, pon, ron), self-draw win (tsumo), simplified han-based scoring,
and imperfect-information authority declarations.

Tiles are represented as (suit, rank) tuples internally. Suited tiles use
ranks 1-9; winds use rank codes (east=1, south=2, west=3, north=4);
dragons use rank codes (red=1, green=2, white=3).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from baize.definition import GameDefinition
from baize.runtime import (
    ComponentData,
    ComponentId,
    GameSession,
    SetZone,
    StackZone,
    CounterZone,
)


# ---------------------------------------------------------------------------
# Tile representation
# ---------------------------------------------------------------------------

# Suit constants
CHARACTERS = "characters"
BAMBOO = "bamboo"
DOTS = "dots"
WIND = "wind"
DRAGON = "dragon"

SUITED_SUITS = [CHARACTERS, BAMBOO, DOTS]
HONOR_SUITS = [WIND, DRAGON]
ALL_SUITS = SUITED_SUITS + HONOR_SUITS

WIND_NAMES = {1: "east", 2: "south", 3: "west", 4: "north"}
DRAGON_NAMES = {1: "red", 2: "green", 3: "white"}


@dataclass(frozen=True)
class Tile:
    suit: str
    rank: int
    red: bool = False

    def __str__(self) -> str:
        if self.suit == WIND:
            return WIND_NAMES.get(self.rank, f"?{self.rank}")
        if self.suit == DRAGON:
            return DRAGON_NAMES.get(self.rank, f"?{self.rank}")
        suffix = {"characters": "m", "bamboo": "s", "dots": "p"}
        r = "0" if self.red else str(self.rank)
        return f"{r}{suffix.get(self.suit, '?')}"

    def is_suited(self) -> bool:
        return self.suit in SUITED_SUITS

    def is_honor(self) -> bool:
        return self.suit in HONOR_SUITS

    def next_in_suit(self) -> Tile | None:
        """Next tile in sequence (for dora calculation). Wraps 9->1."""
        if self.suit in SUITED_SUITS:
            return Tile(self.suit, self.rank % 9 + 1)
        if self.suit == WIND:
            return Tile(WIND, self.rank % 4 + 1)
        if self.suit == DRAGON:
            return Tile(DRAGON, self.rank % 3 + 1)
        return None


def build_full_tileset() -> list[Tile]:
    """Return the 136-tile Riichi set (no flowers/seasons, includes red fives)."""
    tiles: list[Tile] = []
    for suit in SUITED_SUITS:
        for rank in range(1, 10):
            copies = 4
            for copy in range(copies):
                is_red = rank == 5 and copy == 0
                tiles.append(Tile(suit, rank, red=is_red))
    for rank in range(1, 5):
        for _ in range(4):
            tiles.append(Tile(WIND, rank))
    for rank in range(1, 4):
        for _ in range(4):
            tiles.append(Tile(DRAGON, rank))
    return tiles


# ---------------------------------------------------------------------------
# Meld types
# ---------------------------------------------------------------------------

@dataclass
class Meld:
    meld_type: str  # "chi", "pon", "kan", "concealed_kan", "pair"
    tiles: list[Tile]
    open: bool = True

    def __str__(self) -> str:
        return f"{self.meld_type}[{''.join(str(t) for t in self.tiles)}]"


# ---------------------------------------------------------------------------
# Yaku detection (simplified)
# ---------------------------------------------------------------------------

def _count_tiles(tiles: list[Tile]) -> dict[Tile, int]:
    """Count occurrences of each tile (ignoring red flag for matching)."""
    counts: dict[Tile, int] = {}
    for t in tiles:
        key = Tile(t.suit, t.rank)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _can_form_winning_hand(tiles: list[Tile]) -> list[list[Meld]] | None:
    """Check if tiles form 4 melds + 1 pair. Returns possible decompositions.

    Simplified: only checks standard 4-meld-1-pair pattern.
    Tiles should be the 14 tiles (hand + winning tile).
    """
    counts = _count_tiles(tiles)
    results: list[list[Meld]] = []

    # Try each possible pair
    for pair_tile, cnt in list(counts.items()):
        if cnt < 2:
            continue
        remaining = dict(counts)
        remaining[pair_tile] -= 2
        if remaining[pair_tile] == 0:
            del remaining[pair_tile]

        melds = [Meld("pair", [pair_tile, pair_tile], open=False)]
        if _extract_melds(remaining, melds, 4):
            results.append(list(melds))

    return results if results else None


def _extract_melds(
    counts: dict[Tile, int], melds: list[Meld], needed: int
) -> bool:
    """Try to extract `needed` melds (triplets or sequences) from counts."""
    if needed == 0:
        return all(v == 0 for v in counts.values())

    # Find first tile with nonzero count
    first = None
    for t, c in sorted(counts.items(), key=lambda x: (x[0].suit, x[0].rank)):
        if c > 0:
            first = t
            break
    if first is None:
        return False

    # Try triplet
    if counts.get(first, 0) >= 3:
        counts[first] -= 3
        melds.append(Meld("pon", [first, first, first], open=False))
        if _extract_melds(counts, melds, needed - 1):
            return True
        melds.pop()
        counts[first] += 3

    # Try sequence (suited tiles only)
    if first.is_suited() and first.rank <= 7:
        t2 = Tile(first.suit, first.rank + 1)
        t3 = Tile(first.suit, first.rank + 2)
        if counts.get(first, 0) >= 1 and counts.get(t2, 0) >= 1 and counts.get(t3, 0) >= 1:
            counts[first] -= 1
            counts[t2] -= 1
            counts[t3] -= 1
            melds.append(Meld("chi", [first, t2, t3], open=False))
            if _extract_melds(counts, melds, needed - 1):
                return True
            melds.pop()
            counts[first] += 1
            counts[t2] += 1
            counts[t3] += 1

    return False


def _is_seven_pairs(tiles: list[Tile]) -> bool:
    """Check for seven pairs (chiitoitsu)."""
    if len(tiles) != 14:
        return False
    counts = _count_tiles(tiles)
    return len(counts) == 7 and all(v == 2 for v in counts.values())


def _is_thirteen_orphans(tiles: list[Tile]) -> bool:
    """Check for thirteen orphans (kokushi musou)."""
    if len(tiles) != 14:
        return False
    terminals = set()
    for suit in SUITED_SUITS:
        terminals.add(Tile(suit, 1))
        terminals.add(Tile(suit, 9))
    for rank in range(1, 5):
        terminals.add(Tile(WIND, rank))
    for rank in range(1, 4):
        terminals.add(Tile(DRAGON, rank))

    base_tiles = {Tile(t.suit, t.rank) for t in tiles}
    if not terminals.issubset(base_tiles):
        return False
    # Must have exactly 13 unique + 1 duplicate
    counts = _count_tiles(tiles)
    return len(counts) == 13 and any(v == 2 for v in counts.values())


# ---------------------------------------------------------------------------
# Simplified scoring
# ---------------------------------------------------------------------------

YAKU_TABLE: dict[str, int] = {
    "riichi": 1,
    "ippatsu": 1,
    "tsumo": 1,        # menzen tsumo (concealed self-draw)
    "tanyao": 1,        # all simples (no terminals/honors)
    "pinfu": 1,         # no-points hand (all sequences, non-yakuhai pair)
    "iipeiko": 1,       # two identical sequences
    "yakuhai": 1,       # value tiles (per set of dragons/seat wind/round wind)
    "chanta": 2,        # all melds contain a terminal or honor
    "san_anko": 2,      # three concealed triplets
    "toitoi": 2,        # all triplets
    "honitsu": 3,       # half flush (one suit + honors)
    "chinitsu": 6,      # full flush (one suit only)
    "seven_pairs": 2,   # chiitoitsu
    "thirteen_orphans": 13,  # kokushi musou (yakuman)
}


def detect_yaku(
    hand: list[Tile],
    melds: list[Meld],
    winning_tile: Tile,
    is_tsumo: bool,
    is_riichi: bool,
    seat_wind: int,
    round_wind: int,
) -> list[tuple[str, int]]:
    """Detect applicable yaku and return list of (yaku_name, han_value).

    ``hand`` is the concealed tiles (without the winning tile and without
    tiles already locked in open melds).  ``melds`` contains any open (or
    concealed-kan) melds already declared.  The winning tile is provided
    separately.

    The total tile count is:
        len(hand) + 1 (winning) + sum(len(m.tiles) for m in melds) == 14
    """
    # Concealed tiles that need decomposing
    concealed = [Tile(t.suit, t.rank) for t in hand] + [Tile(winning_tile.suit, winning_tile.rank)]

    # All tiles (for whole-hand yaku like tanyao / flush)
    all_tiles_flat: list[Tile] = list(concealed)
    for m in melds:
        all_tiles_flat.extend(Tile(t.suit, t.rank) for t in m.tiles)

    has_open = any(m.open for m in melds)

    # --- Special hands (only when fully concealed, no open melds) ---
    if not melds:
        if _is_thirteen_orphans(all_tiles_flat):
            return [("thirteen_orphans", 13)]

        if _is_seven_pairs(all_tiles_flat):
            found: list[tuple[str, int]] = [("seven_pairs", 2)]
            if all(t.is_suited() and 2 <= t.rank <= 8 for t in all_tiles_flat):
                found.append(("tanyao", 1))
            if is_riichi:
                found.append(("riichi", 1))
            if is_tsumo:
                found.append(("tsumo", 1))
            return found

    # --- Standard 4-meld-1-pair decomposition ---
    # The concealed portion needs (4 - len(melds)) melds + 1 pair.
    needed_melds = 4 - len(melds)
    decompositions = _decompose_concealed(concealed, needed_melds)
    if not decompositions:
        return []

    best_yaku: list[tuple[str, int]] = []
    for decomp in decompositions:
        yaku: list[tuple[str, int]] = []
        all_melds = decomp + melds

        # Riichi
        if is_riichi:
            yaku.append(("riichi", 1))

        # Menzen tsumo
        if is_tsumo and not has_open:
            yaku.append(("tsumo", 1))

        # Tanyao (all simples)
        if all(
            t.is_suited() and 2 <= t.rank <= 8
            for m in all_melds for t in m.tiles
        ):
            yaku.append(("tanyao", 1))

        # Yakuhai (value tiles)
        for m in all_melds:
            if m.meld_type in ("pon", "kan", "concealed_kan"):
                t = m.tiles[0]
                if t.suit == DRAGON:
                    yaku.append(("yakuhai", 1))
                if t.suit == WIND and t.rank == seat_wind:
                    yaku.append(("yakuhai", 1))
                if t.suit == WIND and t.rank == round_wind:
                    yaku.append(("yakuhai", 1))

        # Toitoi (all triplets, no sequences)
        non_pair = [m for m in all_melds if m.meld_type != "pair"]
        if all(m.meld_type in ("pon", "kan", "concealed_kan") for m in non_pair):
            yaku.append(("toitoi", 2))

        # Honitsu (half flush)
        suited_suits = {t.suit for t in all_tiles_flat if t.is_suited()}
        has_honors = any(t.is_honor() for t in all_tiles_flat)
        if len(suited_suits) == 1 and has_honors:
            han = 2 if has_open else 3
            yaku.append(("honitsu", han))

        # Chinitsu (full flush)
        if len(suited_suits) == 1 and not has_honors:
            han = 5 if has_open else 6
            yaku.append(("chinitsu", han))

        total = sum(h for _, h in yaku)
        best_total = sum(h for _, h in best_yaku)
        if total > best_total:
            best_yaku = yaku

    return best_yaku


def _decompose_concealed(
    concealed: list[Tile], needed_melds: int
) -> list[list[Meld]] | None:
    """Decompose concealed tiles into ``needed_melds`` melds + 1 pair.

    When ``needed_melds`` is 4 this is the full-hand check; when open melds
    exist it will be fewer (e.g. 3 melds + 1 pair for one open meld).
    """
    counts = _count_tiles(concealed)
    results: list[list[Meld]] = []

    for pair_tile, cnt in list(counts.items()):
        if cnt < 2:
            continue
        remaining = dict(counts)
        remaining[pair_tile] -= 2
        if remaining[pair_tile] == 0:
            del remaining[pair_tile]
        melds = [Meld("pair", [pair_tile, pair_tile], open=False)]
        if _extract_melds(remaining, melds, needed_melds):
            results.append(list(melds))

    return results if results else None


def count_dora(tiles: list[Tile], dora_indicators: list[Tile]) -> int:
    """Count dora tiles in hand. Also counts red fives as 1 dora each."""
    dora_tiles = set()
    for ind in dora_indicators:
        nxt = ind.next_in_suit()
        if nxt:
            dora_tiles.add(Tile(nxt.suit, nxt.rank))

    count = 0
    for t in tiles:
        if Tile(t.suit, t.rank) in dora_tiles:
            count += 1
        if t.red:
            count += 1
    return count


def calculate_points(han: int, is_dealer: bool) -> int:
    """Simplified point calculation from han count.

    Uses standard Riichi mangan thresholds, ignoring fu for simplicity.
    """
    if han <= 0:
        return 0
    base_multiplier = 4 if is_dealer else 3

    if han >= 13:
        return 8000 * base_multiplier  # yakuman
    if han >= 11:
        return 6000 * base_multiplier  # sanbaiman
    if han >= 8:
        return 4000 * base_multiplier  # baiman
    if han >= 6:
        return 3000 * base_multiplier  # haneman
    if han >= 5:
        return 2000 * base_multiplier  # mangan
    # Sub-mangan: simplified flat values per han
    sub_mangan = {1: 1000, 2: 2000, 3: 4000, 4: 8000}
    base = sub_mangan.get(han, 8000)
    return base * base_multiplier // 4


# ---------------------------------------------------------------------------
# MahjongGame driver
# ---------------------------------------------------------------------------

_GAME_PATH = Path(__file__).parent.parent.parent / "games" / "mahjong.json"


def _load_game() -> GameDefinition:
    return GameDefinition.from_json(_GAME_PATH.read_text())


class MahjongGame:
    """Mahjong game driver for testing draw-discard-claim flow."""

    PLAYERS = ["East", "South", "West", "North"]
    STARTING_SCORE = 25000

    def __init__(self) -> None:
        defn = _load_game()
        self.session = GameSession(defn)
        self.session.runtime.status = "in_progress"

        self.hands: dict[str, list[Tile]] = {p: [] for p in self.PLAYERS}
        self.discards: dict[str, list[Tile]] = {p: [] for p in self.PLAYERS}
        self.melds: dict[str, list[Meld]] = {p: [] for p in self.PLAYERS}
        self.scores: dict[str, int] = {p: self.STARTING_SCORE for p in self.PLAYERS}
        self.wall: list[Tile] = []
        self.dead_wall: list[Tile] = []
        self.dora_indicators: list[Tile] = []
        self.riichi: dict[str, bool] = {p: False for p in self.PLAYERS}
        self.last_discard: Tile | None = None
        self.last_discarder: str | None = None
        self.finished = False
        self.winner: str | None = None
        self.round_wind = 1  # east round

    def current_player(self) -> str:
        p = self.session.current_player()
        assert p is not None
        return p

    def _player_index(self, player: str) -> int:
        return self.PLAYERS.index(player)

    def _next_player(self, player: str) -> str:
        idx = self._player_index(player)
        return self.PLAYERS[(idx + 1) % 4]

    def deal(self, seed: int = 42) -> None:
        """Shuffle and deal 13 tiles to each player. Reserve 14 for dead wall."""
        self.wall = build_full_tileset()
        rng = random.Random(seed)
        rng.shuffle(self.wall)

        for player in self.PLAYERS:
            self.hands[player] = [self.wall.pop() for _ in range(13)]

        self.dead_wall = [self.wall.pop() for _ in range(14)]
        self.dora_indicators = [self.dead_wall[0]]

    def draw(self, player: str | None = None) -> Tile:
        """Draw a tile from the wall for the given player (default: current)."""
        if self.finished:
            raise ValueError("game is finished")
        if not self.wall:
            raise ValueError("wall is empty")
        if player is None:
            player = self.current_player()
        tile = self.wall.pop()
        self.hands[player].append(tile)
        return tile

    def discard(self, player: str, tile: Tile) -> None:
        """Discard a tile from player's hand."""
        if self.finished:
            raise ValueError("game is finished")
        hand = self.hands[player]
        # Find and remove (match by suit/rank, prefer non-red if ambiguous)
        for i, t in enumerate(hand):
            if t.suit == tile.suit and t.rank == tile.rank and t.red == tile.red:
                hand.pop(i)
                break
        else:
            # Try ignoring red flag
            for i, t in enumerate(hand):
                if t.suit == tile.suit and t.rank == tile.rank:
                    hand.pop(i)
                    break
            else:
                raise ValueError(f"{player} does not have {tile} in hand")

        self.discards[player].append(tile)
        self.last_discard = tile
        self.last_discarder = player

    def draw_and_discard(self, player: str | None = None, discard_tile: Tile | None = None) -> Tile:
        """Draw a tile, then discard. If discard_tile is None, discard the drawn tile."""
        if player is None:
            player = self.current_player()
        drawn = self.draw(player)
        to_discard = discard_tile if discard_tile is not None else drawn
        self.discard(player, to_discard)
        self.session.advance_turn()
        return drawn

    def claim_chi(self, claimant: str, tile1: Tile, tile2: Tile) -> Meld:
        """Claim the last discard to form a sequence with two tiles from hand."""
        if self.last_discard is None or self.last_discarder is None:
            raise ValueError("no discard to claim")
        if claimant == self.last_discarder:
            raise ValueError("cannot chi own discard")
        if self._next_player(self.last_discarder) != claimant:
            raise ValueError("chi is only allowed by the next player (shimocha)")

        discard = self.last_discard
        if not discard.is_suited():
            raise ValueError("chi requires suited tiles")

        # Verify sequence
        seq = sorted([discard.rank, tile1.rank, tile2.rank])
        if seq[1] - seq[0] != 1 or seq[2] - seq[1] != 1:
            raise ValueError(f"tiles do not form a sequence: {seq}")
        if tile1.suit != discard.suit or tile2.suit != discard.suit:
            raise ValueError("all tiles in chi must be same suit")

        # Remove from hand
        hand = self.hands[claimant]
        for tile in [tile1, tile2]:
            for i, t in enumerate(hand):
                if t.suit == tile.suit and t.rank == tile.rank:
                    hand.pop(i)
                    break
            else:
                raise ValueError(f"{claimant} does not have {tile}")

        meld = Meld("chi", sorted([discard, tile1, tile2], key=lambda t: t.rank), open=True)
        self.melds[claimant].append(meld)
        self.last_discard = None

        # Set turn to claimant
        self.session.runtime.turn_index = self._player_index(claimant)
        return meld

    def claim_pon(self, claimant: str) -> Meld:
        """Claim the last discard to form a triplet with two from hand."""
        if self.last_discard is None or self.last_discarder is None:
            raise ValueError("no discard to claim")
        if claimant == self.last_discarder:
            raise ValueError("cannot pon own discard")

        discard = self.last_discard
        hand = self.hands[claimant]
        matching = [
            i for i, t in enumerate(hand)
            if t.suit == discard.suit and t.rank == discard.rank
        ]
        if len(matching) < 2:
            raise ValueError(f"{claimant} needs 2 matching tiles for pon, has {len(matching)}")

        # Remove two from hand
        for idx in sorted(matching[:2], reverse=True):
            hand.pop(idx)

        meld = Meld("pon", [discard, discard, discard], open=True)
        self.melds[claimant].append(meld)
        self.last_discard = None

        # Set turn to claimant
        self.session.runtime.turn_index = self._player_index(claimant)
        return meld

    def declare_ron(self, claimant: str) -> dict[str, Any]:
        """Declare win from the last discard."""
        if self.last_discard is None or self.last_discarder is None:
            raise ValueError("no discard to claim for ron")
        if claimant == self.last_discarder:
            raise ValueError("cannot ron own discard")

        winning_tile = self.last_discard
        hand = self.hands[claimant]
        open_melds = self.melds[claimant]
        concealed = [Tile(t.suit, t.rank) for t in hand] + [Tile(winning_tile.suit, winning_tile.rank)]
        all_tiles = list(concealed)
        for m in open_melds:
            all_tiles.extend(Tile(t.suit, t.rank) for t in m.tiles)

        needed_melds = 4 - len(open_melds)
        is_valid = (
            _decompose_concealed(concealed, needed_melds) is not None
            or (not open_melds and _is_seven_pairs(all_tiles))
            or (not open_melds and _is_thirteen_orphans(all_tiles))
        )
        if not is_valid:
            raise ValueError("hand does not form a winning pattern")

        # Check furiten
        discard_set = {Tile(t.suit, t.rank) for t in self.discards[claimant]}
        # Simplified furiten: if the winning tile type is in own discards
        if Tile(winning_tile.suit, winning_tile.rank) in discard_set:
            raise ValueError("furiten: winning tile is in own discard river")

        seat_wind = self._player_index(claimant) + 1
        yaku = detect_yaku(
            hand, self.melds[claimant], winning_tile,
            is_tsumo=False, is_riichi=self.riichi[claimant],
            seat_wind=seat_wind, round_wind=self.round_wind,
        )
        if not yaku:
            raise ValueError("no valid yaku for ron")

        han = sum(h for _, h in yaku)
        dora = count_dora(all_tiles, self.dora_indicators)
        total_han = han + dora
        is_dealer = claimant == "East"
        points = calculate_points(total_han, is_dealer)

        self.scores[self.last_discarder] -= points
        self.scores[claimant] += points
        self.finished = True
        self.winner = claimant

        return {
            "winner": claimant,
            "loser": self.last_discarder,
            "winning_tile": str(winning_tile),
            "yaku": yaku,
            "han": han,
            "dora": dora,
            "total_han": total_han,
            "points": points,
        }

    def declare_tsumo(self, player: str | None = None) -> dict[str, Any]:
        """Declare win by self-draw (player must have 14 tiles in hand + melds)."""
        if player is None:
            player = self.current_player()
        hand = self.hands[player]
        open_melds = self.melds[player]
        total_tiles = len(hand) + sum(len(m.tiles) for m in open_melds)
        if total_tiles < 14:
            raise ValueError(f"tsumo requires 14 tiles total, have {total_tiles}")

        winning_tile = hand[-1]  # last drawn tile
        concealed = hand[:-1]
        concealed_base = [Tile(t.suit, t.rank) for t in hand]
        all_tiles = list(concealed_base)
        for m in open_melds:
            all_tiles.extend(Tile(t.suit, t.rank) for t in m.tiles)

        needed_melds = 4 - len(open_melds)
        is_valid = (
            _decompose_concealed(concealed_base, needed_melds) is not None
            or (not open_melds and _is_seven_pairs(all_tiles))
            or (not open_melds and _is_thirteen_orphans(all_tiles))
        )
        if not is_valid:
            raise ValueError("hand does not form a winning pattern")

        has_open = any(m.open for m in self.melds[player])
        seat_wind = self._player_index(player) + 1
        yaku = detect_yaku(
            concealed, self.melds[player], winning_tile,
            is_tsumo=True, is_riichi=self.riichi[player],
            seat_wind=seat_wind, round_wind=self.round_wind,
        )
        if not yaku:
            raise ValueError("no valid yaku for tsumo")

        han = sum(h for _, h in yaku)
        dora = count_dora(all_tiles, self.dora_indicators)
        total_han = han + dora
        is_dealer = player == "East"
        points = calculate_points(total_han, is_dealer)

        # Tsumo: all others pay
        per_player = points // 3
        for p in self.PLAYERS:
            if p != player:
                self.scores[p] -= per_player
        self.scores[player] += per_player * 3

        self.finished = True
        self.winner = player

        return {
            "winner": player,
            "winning_tile": str(winning_tile),
            "yaku": yaku,
            "han": han,
            "dora": dora,
            "total_han": total_han,
            "points": points,
        }

    def declare_riichi(self, player: str) -> None:
        """Declare riichi (simplified: just mark, no tenpai check)."""
        if any(m.open for m in self.melds[player]):
            raise ValueError("riichi requires a concealed hand")
        if self.scores[player] < 1000:
            raise ValueError("need at least 1000 points for riichi")
        self.riichi[player] = True
        self.scores[player] -= 1000

    def is_furiten(self, player: str) -> bool:
        """Check if player is in furiten (simplified)."""
        discard_types = {Tile(t.suit, t.rank) for t in self.discards[player]}
        # Would need to check all winning tiles, simplified to just checking
        # if any tile the player needs is in their discards
        return len(discard_types) > 0 and any(
            Tile(t.suit, t.rank) in discard_types for t in self.hands[player]
        )

    def tiles_remaining(self) -> int:
        return len(self.wall)

    def hand_size(self, player: str) -> int:
        return len(self.hands[player])


# ---------------------------------------------------------------------------
# Tests: definition
# ---------------------------------------------------------------------------


class TestDefinition:
    def test_loads(self) -> None:
        defn = _load_game()
        assert defn.game.name == "Mahjong (Riichi)"

    def test_four_players(self) -> None:
        defn = _load_game()
        assert defn.game.players == ["East", "South", "West", "North"]

    def test_imperfect_information(self) -> None:
        defn = _load_game()
        assert defn.game.information == "imperfect"

    def test_wall_is_hidden_stack(self) -> None:
        defn = _load_game()
        assert defn.zones["wall"].zone_type == "ordered_stack"
        assert defn.zones["wall"].visibility == "hidden"

    def test_hand_is_per_player_private(self) -> None:
        defn = _load_game()
        assert defn.zones["hand"].per_player is True
        assert defn.zones["hand"].visibility.private == "owner"

    def test_hand_capacity_13(self) -> None:
        defn = _load_game()
        assert defn.zones["hand"].capacity == 13

    def test_discard_is_per_player_public(self) -> None:
        defn = _load_game()
        assert defn.zones["discard"].per_player is True
        assert defn.zones["discard"].visibility == "public"

    def test_melds_is_per_player_public(self) -> None:
        defn = _load_game()
        assert defn.zones["melds"].per_player is True
        assert defn.zones["melds"].visibility == "public"

    def test_dora_indicators_public(self) -> None:
        defn = _load_game()
        assert defn.zones["dora_indicators"].visibility == "public"

    def test_score_is_per_player_counter(self) -> None:
        defn = _load_game()
        assert defn.zones["score"].zone_type == "counter"
        assert defn.zones["score"].per_player is True

    def test_reactive_turn_order(self) -> None:
        defn = _load_game()
        assert defn.turn_order.type == "reactive"

    def test_has_five_phases(self) -> None:
        defn = _load_game()
        assert len(defn.phases) == 5
        names = [p.name for p in defn.phases]
        assert names == ["deal", "draw", "discard", "claim_window", "scoring"]

    def test_server_authority_includes_shuffle_and_deal(self) -> None:
        defn = _load_game()
        assert "shuffle(wall)" in defn.authority.server_only
        assert "deal(wall, hand)" in defn.authority.server_only

    def test_client_verifiable_includes_discard(self) -> None:
        defn = _load_game()
        assert "discard(hand, discard)" in defn.authority.client_verifiable

    def test_wasm_required_for_scoring(self) -> None:
        defn = _load_game()
        assert "yaku_detection" in defn.authority.wasm_required
        assert "han_fu_calculation" in defn.authority.wasm_required

    def test_136_tiles(self) -> None:
        defn = _load_game()
        assert defn.components["tile"].count == 136

    def test_tile_registry_ref(self) -> None:
        defn = _load_game()
        assert defn.components["tile"].registry == "standard:mahjong-136"


# ---------------------------------------------------------------------------
# Tests: session creation
# ---------------------------------------------------------------------------


class TestSession:
    def test_creates_session(self) -> None:
        session = GameSession(_load_game())
        assert session.runtime.status == "setup"

    def test_four_player_seats(self) -> None:
        session = GameSession(_load_game())
        assert list(session.runtime.players.keys()) == ["East", "South", "West", "North"]

    def test_per_player_zones(self) -> None:
        session = GameSession(_load_game())
        for p in ["East", "South", "West", "North"]:
            zones = session.runtime.players[p].zones
            assert "hand" in zones
            assert "discard" in zones
            assert "melds" in zones
            assert "score" in zones

    def test_shared_zones(self) -> None:
        session = GameSession(_load_game())
        assert "wall" in session.runtime.zones
        assert "dead_wall" in session.runtime.zones
        assert "dora_indicators" in session.runtime.zones

    def test_east_starts(self) -> None:
        session = GameSession(_load_game())
        assert session.current_player() == "East"


# ---------------------------------------------------------------------------
# Tests: tile set
# ---------------------------------------------------------------------------


class TestTileSet:
    def test_136_tiles(self) -> None:
        tiles = build_full_tileset()
        assert len(tiles) == 136

    def test_108_suited(self) -> None:
        tiles = build_full_tileset()
        suited = [t for t in tiles if t.is_suited()]
        assert len(suited) == 108

    def test_16_winds(self) -> None:
        tiles = build_full_tileset()
        winds = [t for t in tiles if t.suit == WIND]
        assert len(winds) == 16

    def test_12_dragons(self) -> None:
        tiles = build_full_tileset()
        dragons = [t for t in tiles if t.suit == DRAGON]
        assert len(dragons) == 12

    def test_3_red_fives(self) -> None:
        tiles = build_full_tileset()
        reds = [t for t in tiles if t.red]
        assert len(reds) == 3
        assert all(t.rank == 5 for t in reds)
        assert {t.suit for t in reds} == {CHARACTERS, BAMBOO, DOTS}

    def test_four_copies_each_suited(self) -> None:
        tiles = build_full_tileset()
        for suit in SUITED_SUITS:
            for rank in range(1, 10):
                count = sum(1 for t in tiles if t.suit == suit and t.rank == rank)
                assert count == 4, f"{suit} {rank} has {count} copies"


# ---------------------------------------------------------------------------
# Tests: deal and wall
# ---------------------------------------------------------------------------


class TestDeal:
    def test_deal_gives_13_each(self) -> None:
        game = MahjongGame()
        game.deal()
        for p in game.PLAYERS:
            assert game.hand_size(p) == 13

    def test_deal_deterministic(self) -> None:
        g1 = MahjongGame()
        g1.deal(seed=99)
        g2 = MahjongGame()
        g2.deal(seed=99)
        for p in g1.PLAYERS:
            assert g1.hands[p] == g2.hands[p]

    def test_deal_leaves_correct_wall_size(self) -> None:
        game = MahjongGame()
        game.deal()
        # 136 - 52 (4*13) - 14 (dead wall) = 70
        assert game.tiles_remaining() == 70

    def test_dead_wall_has_14(self) -> None:
        game = MahjongGame()
        game.deal()
        assert len(game.dead_wall) == 14

    def test_one_dora_indicator_after_deal(self) -> None:
        game = MahjongGame()
        game.deal()
        assert len(game.dora_indicators) == 1

    def test_deal_different_seeds_differ(self) -> None:
        g1 = MahjongGame()
        g1.deal(seed=1)
        g2 = MahjongGame()
        g2.deal(seed=2)
        assert g1.hands["East"] != g2.hands["East"]

    def test_all_tiles_accounted_for(self) -> None:
        game = MahjongGame()
        game.deal()
        total = sum(game.hand_size(p) for p in game.PLAYERS)
        total += game.tiles_remaining()
        total += len(game.dead_wall)
        assert total == 136


# ---------------------------------------------------------------------------
# Tests: draw and discard
# ---------------------------------------------------------------------------


class TestDrawDiscard:
    def test_draw_adds_to_hand(self) -> None:
        game = MahjongGame()
        game.deal()
        player = game.current_player()
        assert game.hand_size(player) == 13
        game.draw()
        assert game.hand_size(player) == 14

    def test_draw_removes_from_wall(self) -> None:
        game = MahjongGame()
        game.deal()
        before = game.tiles_remaining()
        game.draw()
        assert game.tiles_remaining() == before - 1

    def test_discard_removes_from_hand(self) -> None:
        game = MahjongGame()
        game.deal()
        player = game.current_player()
        tile = game.draw()
        assert game.hand_size(player) == 14
        game.discard(player, tile)
        assert game.hand_size(player) == 13

    def test_discard_adds_to_river(self) -> None:
        game = MahjongGame()
        game.deal()
        player = game.current_player()
        tile = game.draw()
        game.discard(player, tile)
        assert len(game.discards[player]) == 1
        assert game.discards[player][0] == tile

    def test_discard_invalid_tile_raises(self) -> None:
        game = MahjongGame()
        game.deal()
        player = game.current_player()
        game.draw()
        fake = Tile("nonexistent", 99)
        with pytest.raises(ValueError, match="does not have"):
            game.discard(player, fake)

    def test_draw_and_discard_advances_turn(self) -> None:
        game = MahjongGame()
        game.deal()
        assert game.current_player() == "East"
        game.draw_and_discard()
        assert game.current_player() == "South"

    def test_full_rotation(self) -> None:
        game = MahjongGame()
        game.deal()
        for expected in ["East", "South", "West", "North"]:
            assert game.current_player() == expected
            game.draw_and_discard()
        assert game.current_player() == "East"

    def test_draw_from_empty_wall_raises(self) -> None:
        game = MahjongGame()
        game.deal()
        # Drain the wall
        game.wall.clear()
        with pytest.raises(ValueError, match="wall is empty"):
            game.draw()


# ---------------------------------------------------------------------------
# Tests: chi (sequence claim)
# ---------------------------------------------------------------------------


class TestChi:
    def _setup_chi(self) -> tuple[MahjongGame, Tile, Tile, Tile]:
        """Set up a game where South can chi East's discard."""
        game = MahjongGame()
        game.deal()
        # Give South two tiles that form a sequence with a known discard
        t1 = Tile(BAMBOO, 2)
        t2 = Tile(BAMBOO, 3)
        discard = Tile(BAMBOO, 4)
        game.hands["South"] = [t1, t2] + [Tile(DOTS, i) for i in range(1, 10)] + [Tile(WIND, 1), Tile(WIND, 2)]
        game.hands["East"].append(discard)
        # East discards
        game.discard("East", discard)
        return game, t1, t2, discard

    def test_chi_forms_meld(self) -> None:
        game, t1, t2, discard = self._setup_chi()
        meld = game.claim_chi("South", t1, t2)
        assert meld.meld_type == "chi"
        assert len(meld.tiles) == 3
        assert meld.open is True

    def test_chi_removes_from_hand(self) -> None:
        game, t1, t2, discard = self._setup_chi()
        before = game.hand_size("South")
        game.claim_chi("South", t1, t2)
        assert game.hand_size("South") == before - 2

    def test_chi_sets_turn_to_claimant(self) -> None:
        game, t1, t2, discard = self._setup_chi()
        game.claim_chi("South", t1, t2)
        assert game.current_player() == "South"

    def test_chi_only_shimocha(self) -> None:
        """Only the next player (shimocha) can chi."""
        game, t1, t2, discard = self._setup_chi()
        # West is not shimocha of East
        game.hands["West"] = [t1, t2] + [Tile(DOTS, i) for i in range(1, 10)] + [Tile(WIND, 1), Tile(WIND, 2)]
        with pytest.raises(ValueError, match="shimocha"):
            game.claim_chi("West", t1, t2)

    def test_chi_own_discard_rejected(self) -> None:
        game = MahjongGame()
        game.deal()
        tile = game.draw("East")
        game.discard("East", tile)
        with pytest.raises(ValueError, match="cannot chi own"):
            game.claim_chi("East", Tile(BAMBOO, 1), Tile(BAMBOO, 2))

    def test_chi_honors_rejected(self) -> None:
        """Cannot chi with honor tiles."""
        game = MahjongGame()
        game.deal()
        discard = Tile(WIND, 1)
        game.hands["East"].append(discard)
        game.discard("East", discard)
        with pytest.raises(ValueError, match="suited"):
            game.claim_chi("South", Tile(WIND, 2), Tile(WIND, 3))

    def test_chi_non_sequence_rejected(self) -> None:
        game, _, _, _ = self._setup_chi()
        with pytest.raises(ValueError, match="sequence"):
            game.claim_chi("South", Tile(BAMBOO, 2), Tile(BAMBOO, 6))


# ---------------------------------------------------------------------------
# Tests: pon (triplet claim)
# ---------------------------------------------------------------------------


class TestPon:
    def _setup_pon(self) -> tuple[MahjongGame, Tile]:
        """Set up a game where West can pon East's discard."""
        game = MahjongGame()
        game.deal()
        discard = Tile(CHARACTERS, 7)
        game.hands["West"] = [discard, discard] + [Tile(DOTS, i) for i in range(1, 10)] + [Tile(WIND, 1)]
        game.hands["East"].append(discard)
        game.discard("East", discard)
        return game, discard

    def test_pon_forms_meld(self) -> None:
        game, discard = self._setup_pon()
        meld = game.claim_pon("West")
        assert meld.meld_type == "pon"
        assert len(meld.tiles) == 3

    def test_pon_any_player(self) -> None:
        """Unlike chi, pon can be claimed by any non-discarder."""
        game, discard = self._setup_pon()
        # North also has two matching tiles
        game.hands["North"] = [discard, discard] + [Tile(DOTS, i) for i in range(1, 10)] + [Tile(WIND, 1)]
        meld = game.claim_pon("North")
        assert meld.meld_type == "pon"

    def test_pon_removes_two_from_hand(self) -> None:
        game, discard = self._setup_pon()
        before = game.hand_size("West")
        game.claim_pon("West")
        assert game.hand_size("West") == before - 2

    def test_pon_sets_turn(self) -> None:
        game, _ = self._setup_pon()
        game.claim_pon("West")
        assert game.current_player() == "West"

    def test_pon_own_discard_rejected(self) -> None:
        game, _ = self._setup_pon()
        with pytest.raises(ValueError, match="cannot pon own"):
            game.claim_pon("East")

    def test_pon_insufficient_tiles_rejected(self) -> None:
        game = MahjongGame()
        game.deal()
        discard = Tile(DOTS, 3)
        game.hands["East"].append(discard)
        game.discard("East", discard)
        # South only has 1 matching tile
        game.hands["South"] = [discard] + [Tile(WIND, i) for i in range(1, 5)] * 3
        with pytest.raises(ValueError, match="needs 2"):
            game.claim_pon("South")


# ---------------------------------------------------------------------------
# Tests: winning hand detection
# ---------------------------------------------------------------------------


class TestWinningHand:
    def test_four_melds_one_pair(self) -> None:
        """Standard winning hand: 4 melds + 1 pair."""
        tiles = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),  # chi
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),         # chi
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 7), Tile(CHARACTERS, 7),  # pon
            Tile(WIND, 1), Tile(WIND, 1), Tile(WIND, 1),         # pon
            Tile(DRAGON, 1), Tile(DRAGON, 1),                     # pair
        ]
        result = _can_form_winning_hand(tiles)
        assert result is not None
        assert len(result) > 0

    def test_all_sequences(self) -> None:
        tiles = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(BAMBOO, 4), Tile(BAMBOO, 5), Tile(BAMBOO, 6),
            Tile(DOTS, 1), Tile(DOTS, 2), Tile(DOTS, 3),
            Tile(DOTS, 7), Tile(DOTS, 8), Tile(DOTS, 9),
            Tile(CHARACTERS, 5), Tile(CHARACTERS, 5),
        ]
        result = _can_form_winning_hand(tiles)
        assert result is not None

    def test_all_triplets(self) -> None:
        tiles = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 1), Tile(BAMBOO, 1),
            Tile(DOTS, 3), Tile(DOTS, 3), Tile(DOTS, 3),
            Tile(CHARACTERS, 5), Tile(CHARACTERS, 5), Tile(CHARACTERS, 5),
            Tile(WIND, 2), Tile(WIND, 2), Tile(WIND, 2),
            Tile(DRAGON, 3), Tile(DRAGON, 3),
        ]
        result = _can_form_winning_hand(tiles)
        assert result is not None

    def test_incomplete_hand_rejected(self) -> None:
        """13 tiles is not a winning hand."""
        tiles = [Tile(BAMBOO, i) for i in range(1, 10)] + [
            Tile(DOTS, 1), Tile(DOTS, 2), Tile(DOTS, 3), Tile(DOTS, 4),
        ]
        result = _can_form_winning_hand(tiles)
        assert result is None

    def test_invalid_grouping_rejected(self) -> None:
        """Tiles that cannot form valid melds."""
        tiles = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 1), Tile(BAMBOO, 3),
            Tile(BAMBOO, 3), Tile(BAMBOO, 5), Tile(BAMBOO, 5),
            Tile(BAMBOO, 7), Tile(BAMBOO, 7), Tile(BAMBOO, 9),
            Tile(BAMBOO, 9), Tile(DOTS, 1), Tile(DOTS, 1),
            Tile(DOTS, 3), Tile(DOTS, 5),
        ]
        result = _can_form_winning_hand(tiles)
        assert result is None

    def test_seven_pairs(self) -> None:
        tiles = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 1),
            Tile(BAMBOO, 3), Tile(BAMBOO, 3),
            Tile(DOTS, 5), Tile(DOTS, 5),
            Tile(DOTS, 7), Tile(DOTS, 7),
            Tile(CHARACTERS, 2), Tile(CHARACTERS, 2),
            Tile(WIND, 1), Tile(WIND, 1),
            Tile(DRAGON, 2), Tile(DRAGON, 2),
        ]
        assert _is_seven_pairs(tiles) is True

    def test_seven_pairs_requires_7_distinct(self) -> None:
        """Four of a kind counts as 2 pairs but only 6 distinct tiles."""
        tiles = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 1),
            Tile(BAMBOO, 1), Tile(BAMBOO, 1),  # 4 of same = not 7 distinct pairs
            Tile(DOTS, 5), Tile(DOTS, 5),
            Tile(DOTS, 7), Tile(DOTS, 7),
            Tile(CHARACTERS, 2), Tile(CHARACTERS, 2),
            Tile(WIND, 1), Tile(WIND, 1),
            Tile(DRAGON, 2), Tile(DRAGON, 2),
        ]
        assert _is_seven_pairs(tiles) is False

    def test_thirteen_orphans(self) -> None:
        tiles = [
            Tile(CHARACTERS, 1), Tile(CHARACTERS, 9),
            Tile(BAMBOO, 1), Tile(BAMBOO, 9),
            Tile(DOTS, 1), Tile(DOTS, 9),
            Tile(WIND, 1), Tile(WIND, 2), Tile(WIND, 3), Tile(WIND, 4),
            Tile(DRAGON, 1), Tile(DRAGON, 2), Tile(DRAGON, 3),
            Tile(WIND, 1),  # duplicate for the pair
        ]
        assert _is_thirteen_orphans(tiles) is True

    def test_thirteen_orphans_missing_one(self) -> None:
        tiles = [
            Tile(CHARACTERS, 1), Tile(CHARACTERS, 9),
            Tile(BAMBOO, 1), Tile(BAMBOO, 9),
            Tile(DOTS, 1), Tile(DOTS, 9),
            Tile(WIND, 1), Tile(WIND, 2), Tile(WIND, 3), Tile(WIND, 4),
            Tile(DRAGON, 1), Tile(DRAGON, 2),
            Tile(DOTS, 5), Tile(DOTS, 5),  # not a terminal
        ]
        assert _is_thirteen_orphans(tiles) is False


# ---------------------------------------------------------------------------
# Tests: yaku detection
# ---------------------------------------------------------------------------


class TestYaku:
    def test_tanyao(self) -> None:
        """All simples (no terminals or honors)."""
        hand = [
            Tile(BAMBOO, 2), Tile(BAMBOO, 3), Tile(BAMBOO, 4),
            Tile(DOTS, 3), Tile(DOTS, 4), Tile(DOTS, 5),
            Tile(CHARACTERS, 6), Tile(CHARACTERS, 7), Tile(CHARACTERS, 8),
            Tile(BAMBOO, 5), Tile(BAMBOO, 5), Tile(BAMBOO, 5),
            Tile(DOTS, 2),
        ]
        winning = Tile(DOTS, 2)
        yaku = detect_yaku(hand, [], winning, is_tsumo=True, is_riichi=False,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "tanyao" in names
        assert "tsumo" in names

    def test_yakuhai_dragon(self) -> None:
        """Triplet of dragons grants yakuhai.

        10 concealed + 1 winning + 3 open pon = 14 total.
        """
        hand = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(BAMBOO, 5),
        ]
        dragon_pon = Meld("pon", [Tile(DRAGON, 1)] * 3, open=True)
        winning = Tile(BAMBOO, 5)
        yaku = detect_yaku(hand, [dragon_pon], winning, is_tsumo=False, is_riichi=False,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "yakuhai" in names

    def test_toitoi(self) -> None:
        """All triplets hand."""
        hand = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 1), Tile(BAMBOO, 1),
            Tile(DOTS, 3), Tile(DOTS, 3), Tile(DOTS, 3),
            Tile(CHARACTERS, 5), Tile(CHARACTERS, 5), Tile(CHARACTERS, 5),
            Tile(WIND, 2), Tile(WIND, 2), Tile(WIND, 2),
            Tile(DRAGON, 3),
        ]
        winning = Tile(DRAGON, 3)
        yaku = detect_yaku(hand, [], winning, is_tsumo=True, is_riichi=False,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "toitoi" in names

    def test_chinitsu(self) -> None:
        """Full flush (all one suit)."""
        hand = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(BAMBOO, 4), Tile(BAMBOO, 5), Tile(BAMBOO, 6),
            Tile(BAMBOO, 7), Tile(BAMBOO, 8), Tile(BAMBOO, 9),
            Tile(BAMBOO, 1), Tile(BAMBOO, 1), Tile(BAMBOO, 1),
            Tile(BAMBOO, 9),
        ]
        winning = Tile(BAMBOO, 9)
        yaku = detect_yaku(hand, [], winning, is_tsumo=False, is_riichi=False,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "chinitsu" in names

    def test_honitsu(self) -> None:
        """Half flush (one suit + honors)."""
        hand = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(BAMBOO, 4), Tile(BAMBOO, 5), Tile(BAMBOO, 6),
            Tile(BAMBOO, 7), Tile(BAMBOO, 8), Tile(BAMBOO, 9),
            Tile(WIND, 1), Tile(WIND, 1), Tile(WIND, 1),
            Tile(BAMBOO, 9),
        ]
        winning = Tile(BAMBOO, 9)
        yaku = detect_yaku(hand, [], winning, is_tsumo=False, is_riichi=False,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "honitsu" in names

    def test_riichi_yaku(self) -> None:
        """Riichi declaration grants riichi yaku."""
        hand = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(BAMBOO, 5), Tile(BAMBOO, 5), Tile(BAMBOO, 5),
            Tile(DOTS, 2),
        ]
        winning = Tile(DOTS, 2)
        yaku = detect_yaku(hand, [], winning, is_tsumo=False, is_riichi=True,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "riichi" in names

    def test_no_yaku_hand(self) -> None:
        """A hand with no yaku returns empty list."""
        # Open hand with mixed suits, no special patterns
        hand = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8),
        ]
        # Open meld means no tsumo yaku, and mixed suits means no flush
        open_chi = Meld("chi", [Tile(CHARACTERS, 1), Tile(CHARACTERS, 2), Tile(CHARACTERS, 3)], open=True)
        winning = Tile(CHARACTERS, 9)
        yaku = detect_yaku(hand, [open_chi], winning, is_tsumo=False, is_riichi=False,
                          seat_wind=2, round_wind=1)
        assert yaku == []

    def test_thirteen_orphans_yaku(self) -> None:
        hand = [
            Tile(CHARACTERS, 1), Tile(CHARACTERS, 9),
            Tile(BAMBOO, 1), Tile(BAMBOO, 9),
            Tile(DOTS, 1), Tile(DOTS, 9),
            Tile(WIND, 1), Tile(WIND, 2), Tile(WIND, 3), Tile(WIND, 4),
            Tile(DRAGON, 1), Tile(DRAGON, 2), Tile(DRAGON, 3),
        ]
        winning = Tile(WIND, 1)  # pair tile
        yaku = detect_yaku(hand, [], winning, is_tsumo=True, is_riichi=False,
                          seat_wind=1, round_wind=1)
        names = [y[0] for y in yaku]
        assert "thirteen_orphans" in names
        total_han = sum(h for _, h in yaku)
        assert total_han == 13


# ---------------------------------------------------------------------------
# Tests: dora counting
# ---------------------------------------------------------------------------


class TestDora:
    def test_dora_indicator_gives_next_tile(self) -> None:
        indicator = Tile(BAMBOO, 3)
        nxt = indicator.next_in_suit()
        assert nxt == Tile(BAMBOO, 4)

    def test_dora_wraps_9_to_1(self) -> None:
        indicator = Tile(DOTS, 9)
        nxt = indicator.next_in_suit()
        assert nxt == Tile(DOTS, 1)

    def test_wind_wraps(self) -> None:
        indicator = Tile(WIND, 4)  # north
        nxt = indicator.next_in_suit()
        assert nxt == Tile(WIND, 1)  # east

    def test_dragon_wraps(self) -> None:
        indicator = Tile(DRAGON, 3)  # white
        nxt = indicator.next_in_suit()
        assert nxt == Tile(DRAGON, 1)  # red

    def test_count_dora_in_hand(self) -> None:
        hand = [Tile(BAMBOO, 4), Tile(BAMBOO, 4), Tile(DOTS, 1)]
        indicators = [Tile(BAMBOO, 3)]  # dora = bamboo 4
        assert count_dora(hand, indicators) == 2

    def test_red_five_counts_as_dora(self) -> None:
        hand = [Tile(BAMBOO, 5, red=True)]
        assert count_dora(hand, []) == 1

    def test_red_five_plus_indicator(self) -> None:
        """Red five counts as dora even when it's also the indicator dora."""
        hand = [Tile(BAMBOO, 5, red=True)]
        indicators = [Tile(BAMBOO, 4)]  # dora = bamboo 5
        assert count_dora(hand, indicators) == 2  # 1 from indicator + 1 from red


# ---------------------------------------------------------------------------
# Tests: scoring
# ---------------------------------------------------------------------------


class TestScoring:
    def test_mangan_points_dealer(self) -> None:
        assert calculate_points(5, is_dealer=True) == 4 * 2000

    def test_mangan_points_non_dealer(self) -> None:
        assert calculate_points(5, is_dealer=False) == 3 * 2000

    def test_yakuman_points(self) -> None:
        assert calculate_points(13, is_dealer=True) == 4 * 8000
        assert calculate_points(13, is_dealer=False) == 3 * 8000

    def test_haneman(self) -> None:
        assert calculate_points(6, is_dealer=False) == 3 * 3000
        assert calculate_points(7, is_dealer=False) == 3 * 3000

    def test_baiman(self) -> None:
        assert calculate_points(8, is_dealer=False) == 3 * 4000

    def test_sanbaiman(self) -> None:
        assert calculate_points(11, is_dealer=False) == 3 * 6000

    def test_zero_han(self) -> None:
        assert calculate_points(0, is_dealer=False) == 0


# ---------------------------------------------------------------------------
# Tests: ron (win from discard)
# ---------------------------------------------------------------------------


class TestRon:
    def test_ron_valid_hand(self) -> None:
        game = MahjongGame()
        game.deal()
        # Set up West with a tenpai hand
        game.hands["West"] = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(DRAGON, 1), Tile(DRAGON, 1), Tile(DRAGON, 1),
            Tile(BAMBOO, 5),
        ]
        game.melds["West"] = []
        # East discards the winning tile
        winning_tile = Tile(BAMBOO, 5)
        game.hands["East"].append(winning_tile)
        game.discard("East", winning_tile)
        result = game.declare_ron("West")
        assert result["winner"] == "West"
        assert result["loser"] == "East"
        assert game.finished is True

    def test_ron_furiten_rejected(self) -> None:
        game = MahjongGame()
        game.deal()
        game.hands["South"] = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(DRAGON, 1), Tile(DRAGON, 1), Tile(DRAGON, 1),
            Tile(BAMBOO, 5),
        ]
        # South previously discarded bamboo 5 (furiten)
        game.discards["South"] = [Tile(BAMBOO, 5)]
        game.melds["South"] = []
        winning_tile = Tile(BAMBOO, 5)
        game.hands["East"].append(winning_tile)
        game.discard("East", winning_tile)
        with pytest.raises(ValueError, match="furiten"):
            game.declare_ron("South")

    def test_ron_no_yaku_rejected(self) -> None:
        game = MahjongGame()
        game.deal()
        # Open hand with no yaku: mixed suits, open meld, no flush/value tiles
        # 10 concealed + 3 in open chi + 1 winning = 14
        game.hands["North"] = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(DOTS, 2),
        ]
        game.melds["North"] = [
            Meld("chi", [Tile(CHARACTERS, 1), Tile(CHARACTERS, 2), Tile(CHARACTERS, 3)], open=True),
        ]
        game.discards["North"] = []
        winning_tile = Tile(DOTS, 2)
        game.hands["East"].append(winning_tile)
        game.discard("East", winning_tile)
        with pytest.raises(ValueError, match="no valid yaku"):
            game.declare_ron("North")

    def test_ron_transfers_points(self) -> None:
        game = MahjongGame()
        game.deal()
        game.hands["South"] = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(DRAGON, 1), Tile(DRAGON, 1), Tile(DRAGON, 1),
            Tile(BAMBOO, 5),
        ]
        game.melds["South"] = []
        winning_tile = Tile(BAMBOO, 5)
        game.hands["East"].append(winning_tile)
        game.discard("East", winning_tile)
        east_before = game.scores["East"]
        south_before = game.scores["South"]
        result = game.declare_ron("South")
        assert game.scores["East"] < east_before
        assert game.scores["South"] > south_before
        assert game.scores["South"] - south_before == result["points"]


# ---------------------------------------------------------------------------
# Tests: tsumo (self-draw win)
# ---------------------------------------------------------------------------


class TestTsumo:
    def test_tsumo_valid_hand(self) -> None:
        game = MahjongGame()
        game.deal()
        game.hands["East"] = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(DRAGON, 1), Tile(DRAGON, 1), Tile(DRAGON, 1),
            Tile(BAMBOO, 5),
        ]
        game.melds["East"] = []
        # Simulate drawing the winning tile
        winning = Tile(BAMBOO, 5)
        game.hands["East"].append(winning)
        result = game.declare_tsumo("East")
        assert result["winner"] == "East"
        assert game.finished is True

    def test_tsumo_requires_14_tiles(self) -> None:
        game = MahjongGame()
        game.deal()
        game.hands["East"] = [Tile(BAMBOO, i) for i in range(1, 10)]  # only 9
        with pytest.raises(ValueError, match="14 tiles"):
            game.declare_tsumo("East")

    def test_tsumo_all_others_pay(self) -> None:
        game = MahjongGame()
        game.deal()
        game.hands["East"] = [
            Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3),
            Tile(DOTS, 4), Tile(DOTS, 5), Tile(DOTS, 6),
            Tile(CHARACTERS, 7), Tile(CHARACTERS, 8), Tile(CHARACTERS, 9),
            Tile(DRAGON, 1), Tile(DRAGON, 1), Tile(DRAGON, 1),
            Tile(BAMBOO, 5), Tile(BAMBOO, 5),
        ]
        game.melds["East"] = []
        before = dict(game.scores)
        result = game.declare_tsumo("East")
        # All others should lose points
        for p in ["South", "West", "North"]:
            assert game.scores[p] < before[p]
        assert game.scores["East"] > before["East"]


# ---------------------------------------------------------------------------
# Tests: riichi
# ---------------------------------------------------------------------------


class TestRiichi:
    def test_riichi_costs_1000(self) -> None:
        game = MahjongGame()
        game.deal()
        before = game.scores["East"]
        game.declare_riichi("East")
        assert game.scores["East"] == before - 1000

    def test_riichi_marks_player(self) -> None:
        game = MahjongGame()
        game.deal()
        assert game.riichi["East"] is False
        game.declare_riichi("East")
        assert game.riichi["East"] is True

    def test_riichi_requires_concealed_hand(self) -> None:
        game = MahjongGame()
        game.deal()
        game.melds["East"] = [
            Meld("chi", [Tile(BAMBOO, 1), Tile(BAMBOO, 2), Tile(BAMBOO, 3)], open=True)
        ]
        with pytest.raises(ValueError, match="concealed"):
            game.declare_riichi("East")

    def test_riichi_requires_1000_points(self) -> None:
        game = MahjongGame()
        game.deal()
        game.scores["East"] = 500
        with pytest.raises(ValueError, match="1000 points"):
            game.declare_riichi("East")


# ---------------------------------------------------------------------------
# Tests: full game flow
# ---------------------------------------------------------------------------


class TestFullGame:
    def test_deal_draw_discard_cycle(self) -> None:
        """Play several draw-discard turns without claims."""
        game = MahjongGame()
        game.deal()
        for _ in range(4):
            game.draw_and_discard()
        # After 4 turns, each player played once
        assert game.tiles_remaining() == 66  # 70 - 4
        assert game.current_player() == "East"

    def test_chi_then_discard(self) -> None:
        """Chi claim followed by mandatory discard."""
        game = MahjongGame()
        game.deal()
        # East draws and discards bamboo 4
        discard = Tile(BAMBOO, 4)
        game.hands["East"].append(discard)
        game.discard("East", discard)
        # South has bamboo 2, 3
        game.hands["South"] = [
            Tile(BAMBOO, 2), Tile(BAMBOO, 3),
        ] + [Tile(DOTS, i) for i in range(1, 10)] + [Tile(WIND, 1), Tile(WIND, 2)]
        game.claim_chi("South", Tile(BAMBOO, 2), Tile(BAMBOO, 3))
        assert game.current_player() == "South"
        assert len(game.melds["South"]) == 1
        # South must discard (11 tiles in hand after chi removed 2)
        game.discard("South", Tile(DOTS, 1))
        assert game.hand_size("South") == 10

    def test_game_ends_on_empty_wall(self) -> None:
        """Exhaustive draw when wall runs out."""
        game = MahjongGame()
        game.deal()
        # Drain wall to simulate exhaustive draw
        turns = game.tiles_remaining()
        for _ in range(turns):
            game.draw_and_discard()
        assert game.tiles_remaining() == 0

    def test_wire_state_roundtrip(self) -> None:
        """Wire state serialization works after setup."""
        game = MahjongGame()
        wire = game.session.to_wire_state()
        assert "East" in wire.players
        assert wire.players["East"].zones is not None
        assert "hand" in wire.players["East"].zones
