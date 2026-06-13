"""Loaded external resources for a game session."""

from __future__ import annotations

from pathlib import Path

from baize.definition import ResourceDef
from baize.error import IllegalActionError

MAX_WORD_LIST_ENTRIES = 500_000
MAX_WORD_LENGTH = 64
MAX_RESOURCE_FILE_BYTES = 50 * 1024 * 1024  # 50 MB


class ResourceStore:
    """Loaded external resources for a game session."""

    def __init__(self) -> None:
        self._word_lists: dict[str, set[str]] = {}

    @staticmethod
    def empty() -> ResourceStore:
        return ResourceStore()

    @staticmethod
    def load(
        resources: dict[str, ResourceDef],
        base_dir: Path,
    ) -> ResourceStore:
        store = ResourceStore()
        for key, resource in resources.items():
            if resource.resource_type == "word_list":
                path = base_dir / "registry" / "dictionaries" / f"{resource.name}.txt"
                words = store._load_word_list(path)
                store._word_lists[key] = words
            else:
                raise IllegalActionError(
                    f"unknown resource type: {resource.resource_type!r} "
                    f"for resource {key!r}"
                )
        return store

    def word_valid(self, resource_name: str, word: str) -> bool:
        word_list = self._word_lists.get(resource_name)
        if word_list is None:
            raise IllegalActionError(
                f"word list resource {resource_name!r} not loaded"
            )
        return word.upper() in word_list

    @staticmethod
    def _load_word_list(path: Path) -> set[str]:
        if not path.exists():
            raise IllegalActionError(f"resource file not found: {path}")

        file_size = path.stat().st_size
        if file_size > MAX_RESOURCE_FILE_BYTES:
            raise IllegalActionError(
                f"resource file {path} is {file_size} bytes, "
                f"exceeds limit of {MAX_RESOURCE_FILE_BYTES} bytes"
            )

        words: set[str] = set()
        content = path.read_text(encoding="utf-8")
        for line in content.splitlines():
            word = line.strip().upper()
            if not word:
                continue
            if len(word) > MAX_WORD_LENGTH:
                raise IllegalActionError(
                    f"word too long ({len(word)} chars, max {MAX_WORD_LENGTH})"
                )
            if len(words) >= MAX_WORD_LIST_ENTRIES:
                raise IllegalActionError(
                    f"word list exceeds {MAX_WORD_LIST_ENTRIES} entries"
                )
            words.add(word)
        return words
