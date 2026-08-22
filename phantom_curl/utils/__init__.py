from collections.abc import MutableMapping
from typing import Iterator

from phantom_curl.utils.storagestate_validation import is_valid_origin

class CaseInsensitiveDict(MutableMapping):
    """
    A dict-like mapping where key lookups are case-insensitive.

    Preserves the original casing of keys for iteration/display,
    but treats "Content-Type" and "content-type" as the same key
    for get/set/delete/contains operations.
    """

    def __init__(self, data=None):
        self._store = {}  # lowercase_key -> (original_key, value)
        if data:
            for key, value in dict(data).items():
                self[key] = value

    def __setitem__(self, key: str, value: str) -> None:
        self._store[key.lower()] = (key, value)

    def __getitem__(self, key: str) -> str:
        return self._store[key.lower()][1]

    def __delitem__(self, key: str) -> None:
        del self._store[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return (original_key for original_key, _ in self._store.values())

    def __len__(self) -> int:
        return len(self._store)

__all__ = [
    "CaseInsensitiveDict",
    "is_valid_origin"
]