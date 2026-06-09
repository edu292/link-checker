import operator
import re
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum, auto

from utils import build_datetime_regexes


class Operator(StrEnum):
    LT = '<'
    GT = '>'
    LE = '<='
    GE = '>='
    EQ = '=='
    NE = '!='


class Assertion(StrEnum):
    REQUIRED = 'required'
    FORBIDDEN = 'forbidden'


OPERATOR_MAP = {
    Operator.LT: operator.lt,
    Operator.GT: operator.gt,
    Operator.LE: operator.le,
    Operator.GE: operator.ge,
    Operator.EQ: operator.eq,
    Operator.NE: operator.ne,
}


@dataclass(slots=True)
class CompiledCheck:
    error: str
    targets: list[str | datetime]
    assertion: Assertion
    screenshot: bool
    _pattern: re.Pattern | None = None

    @property
    def pattern(self) -> re.Pattern:
        if self._pattern is not None:
            return self._pattern

        parts = []
        for target in self.targets:
            if isinstance(target, datetime):
                parts.extend(build_datetime_regexes(target))
            else:
                parts.append(re.escape(str(target)))

        regex = rf'\b({"|".join(parts)})\b'
        self._pattern = re.compile(regex)
        return self._pattern


@dataclass(slots=True)
class ScrapeTask:
    row: int
    url: str
    checks: list[CompiledCheck]


class Status(IntEnum):
    OK = auto()
    NETWORK_ERROR = auto()
    NOT_FOUND = auto()
    CLIENT_ERROR = auto()
    SERVER_ERROR = auto()
    RUNTIME_ERROR = auto()
    TIMEOUT = auto()
    EMPTY_RESPONSE = auto()
    CONTENT_ERROR = auto()


@dataclass(slots=True)
class LinkResult:
    url: str
    status: Status
    http_code: int | None = None
    reason: str | None = None
    matched_word: str | None = None
    screenshot: bytes | None = None

    def __str__(self) -> str:
        return f'{self.status.name} {self.http_code} {self.reason}\n{self.url}'
