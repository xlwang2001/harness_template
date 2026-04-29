"""Validation primitives shared by scaffold validators."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationMessage:
    level: str
    path: Path
    message: str

    def format(self, root: Path) -> str:
        try:
            display = self.path.relative_to(root)
        except ValueError:
            display = self.path
        return f"{self.level}: {display}: {self.message}"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def missing_file(root: Path, relative: str) -> ValidationMessage | None:
    path = root / relative
    if not path.is_file():
        return ValidationMessage("ERROR", path, "required file is missing")
    return None
