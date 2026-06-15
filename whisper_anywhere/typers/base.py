from abc import ABC, abstractmethod


class Typer(ABC):
    @abstractmethod
    def type_text(self, text: str) -> None: ...

    @abstractmethod
    def backspace(self, n: int) -> None: ...
