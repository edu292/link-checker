from enum import StrEnum, nonmember
from pathlib import Path
from typing import Literal

import msgspec

from shared import Assertion, Operator
from utils import clean_text


class Require(StrEnum):
    ANY = 'any'
    ALL = 'all'


class FilterType(StrEnum):
    DATE = 'date'
    NUMBER = 'number'
    TEXT = 'text'

    tag_field = nonmember('type')


class CheckMatch(StrEnum):
    COLUMN = 'column'
    TEXT = 'text'

    tag_field = nonmember('match_by')


class BrowserConfig(msgspec.Struct):
    max_concurrent_pages: int = 2
    block_media: bool = True
    block_third_party: bool = False
    page_load_timeout: int = 15000
    network_idle_timeout: int = 5000


class ScreenshotConfig(msgspec.Struct):
    enabled: bool = True
    delay: int = 1500
    full_page: bool = False
    quality: int = 50
    format: Literal['jpeg', 'png'] = 'jpeg'


class SmtpConfig(msgspec.Struct):
    host: str
    to_addresses: list[str]
    enabled: bool = True
    port: int = 587
    user: str = ''
    password: str = ''
    from_address: str | None = None

    def __post_init__(self):
        if not self.from_address:
            if not self.user:
                raise ValueError('from_address mandatory when user omitted.')
            self.from_address = self.user


class SpreadsheetConfig(msgspec.Struct):
    url: str
    link_column: str
    sheet: str | None = None

    def __post_init__(self):
        if self.sheet is not None:
            self.sheet = clean_text(self.sheet)


class FilterBase(msgspec.Struct, tag_field=FilterType.tag_field):
    column: str
    operator: Operator

    def __post_init__(self):
        self.column = clean_text(self.column)


class NumberFilter(FilterBase, tag=FilterType.NUMBER.value):
    value: int | float


class TextFilter(FilterBase, tag=FilterType.TEXT.value):
    value: str


class DateFilter(FilterBase, tag=FilterType.DATE.value):
    value: str


FilterConfig = NumberFilter | TextFilter | DateFilter


class Check(msgspec.Struct, kw_only=True, tag_field=CheckMatch.tag_field):
    error: str
    screenshot: bool = True


class MatchTextCheck(Check, tag=CheckMatch.TEXT.value):
    text: str | list[str]
    assertion: Assertion | None = None
    if_column: str | None = None
    if_value: str | int | float | None = None
    if_require: Require | None = None
    if_operator: Operator | None = None

    def __post_init__(self):
        raw_text = [self.text] if isinstance(self.text, str) else self.text
        self.text = [clean_text(t) for t in raw_text]

        if not self.if_column:
            if any(x is not None for x in (self.if_value, self.if_require, self.if_operator)):
                raise ValueError(f"CHECK '{self.error}': if_value, if_require, if_operation require if_column.")
            self.assertion = self.assertion or Assertion.FORBIDDEN
            return

        self.if_column = clean_text(self.if_column)

        if self.if_value is None:
            raise ValueError(f"CHECK '{self.error}': if_column requires if_value.")

        self.assertion = self.assertion or Assertion.REQUIRED
        self.if_operator = self.if_operator or Operator.EQ

        if isinstance(self.if_value, str):
            self.if_value = clean_text(self.if_value)

        if self.if_require is None:
            self.if_require = Require.ANY

    @property
    def is_conditional(self):
        return self.if_column is not None


class MatchColumnCheck(Check, tag=CheckMatch.COLUMN.value):
    column: str
    assertion: Assertion = Assertion.REQUIRED

    def __post_init__(self):
        self.column = clean_text(self.column)


CheckConfig = MatchTextCheck | MatchColumnCheck


class AppConfig(msgspec.Struct):
    spreadsheet: SpreadsheetConfig
    screenshot: ScreenshotConfig
    browser: BrowserConfig
    smtp: SmtpConfig
    filters: list[FilterConfig] = []
    checks: list[CheckConfig] = []


def load_config(path: str | Path) -> AppConfig:
    with open(path, 'rb') as f:
        return msgspec.toml.decode(f.read(), type=AppConfig)
