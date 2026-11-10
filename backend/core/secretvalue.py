"""A wrapper that keeps secret values out of repr, str, logs and error text (AD-05, MH-05)."""

from __future__ import annotations


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "SecretValue(***)"

    __str__ = __repr__

    def __reduce__(self) -> str | tuple[object, ...]:
        raise TypeError("SecretValue cannot be pickled")
