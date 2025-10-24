from dataclasses import dataclass
from typing import Optional


@dataclass
class Event:
    type: str


@dataclass
class Rotate(Event):
    delta: int


@dataclass
class Button(Event):
    name: str  # 'confirm' | 'back' | 'push'


@dataclass
class Tick(Event):
    pass


@dataclass
class TaskDone(Event):
    ok: bool
    message: Optional[str] = None
