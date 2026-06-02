from __future__ import annotations

from dataclasses import dataclass


@dataclass
class JsoncSyntaxError(Exception):
    message: str
    offset: int
    line: int
    column: int
    filename: str | None = None

    def __str__(self) -> str:
        location = f"{self.line}:{self.column}"
        if self.filename:
            location = f"{self.filename}:{location}"
        return f"{location}: {self.message}"
