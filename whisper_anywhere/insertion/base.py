from abc import ABC, abstractmethod


class TextInserter(ABC):
    """Delivers one finished transcript to the focused application."""

    @abstractmethod
    def insert_text(self, text: str) -> bool:
        """Deliver one transcript; True when it reached the focused application."""
        ...
