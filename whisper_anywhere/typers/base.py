from abc import ABC, abstractmethod


class Typer(ABC):
    @abstractmethod
    def type_text(self, text: str) -> None: ...
