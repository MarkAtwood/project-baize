"""Exception hierarchy for the Baize game engine."""


class BaizeError(Exception):
    """Base exception for all Baize errors."""


class ParseError(BaizeError):
    """Failed to parse a game definition, state, or action from JSON."""


class ValidationError(BaizeError):
    """The parsed structure is syntactically valid JSON but semantically invalid."""


class UnknownZoneError(BaizeError):
    """Referenced a zone name that does not exist in the game definition."""

    def __init__(self, zone: str) -> None:
        super().__init__(f"unknown zone: {zone}")
        self.zone = zone


class UnknownComponentError(BaizeError):
    """Referenced a component type that does not exist in the game definition."""

    def __init__(self, component: str) -> None:
        super().__init__(f"unknown component type: {component}")
        self.component = component


class IllegalActionError(BaizeError):
    """Attempted an action that is not legal in the current game state."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"illegal action: {reason}")
        self.reason = reason
