import warnings
from enum import StrEnum, nonmember

import msgspec

from utils import OperatorType, clean_text


class RuleType(StrEnum):
    REQUIRED = 'required'
    FORBIDDEN = 'forbidden'


class MatchMode(StrEnum):
    ANY = 'any'
    ALL = 'all'


class FilterType(StrEnum):
    DATE = 'date'
    NUMBER = 'number'
    TEXT = 'text'

    tag_field = nonmember('type')


class RuleKind(StrEnum):
    COLUMN = 'column'
    STATIC = 'static'
    CONDITIONAL = 'conditional'

    tag_field = nonmember('kind')


class SettingsConfig(msgspec.Struct):
    max_concurrent_pages: int = 2
    page_load_timeout: int = 15000
    network_idle_timeout: int = 5000
    ui_settle_delay: int = 1500
    send_email: bool = True
    take_screenshots: bool | None = None

    def __post_init__(self):
        if not self.send_email:
            if self.take_screenshots is True:
                warnings.warn('SETTINGS: take_screenshots has no effect if send_email is set to false.', stacklevel=2)
            self.take_screenshots = False
        elif self.take_screenshots is None:
            self.take_screenshots = True


class SmtpConfig(msgspec.Struct):
    host: str
    to_addresses: list[str]
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
    operator: OperatorType

    def __post_init__(self):
        self.column = clean_text(self.column)


class NumberFilter(FilterBase, tag=FilterType.NUMBER.value):
    value: int | float


class TextFilter(FilterBase, tag=FilterType.TEXT.value):
    value: str


class DateFilter(FilterBase, tag=FilterType.DATE.value):
    value: str


FilterConfig = NumberFilter | TextFilter | DateFilter


class RuleBase(msgspec.Struct, kw_only=True, tag_field=RuleKind.tag_field):
    name: str
    screenshot: bool = False


class StaticRule(RuleBase, tag=RuleKind.STATIC.value):
    words: list[str]
    type: RuleType = RuleType.FORBIDDEN

    def __post_init__(self):
        self.words = [clean_text(word) for word in self.words]


class ColumnRule(RuleBase, tag=RuleKind.COLUMN.value):
    column: str

    def __post_init__(self):
        self.column = clean_text(self.column)


class ConditionalRule(RuleBase, tag=RuleKind.CONDITIONAL.value):
    target_column: str
    test_value: str | int | float | list[str | int | float]
    words: list[str]
    type: RuleType = RuleType.REQUIRED
    operator: OperatorType = OperatorType.EQ
    match_mode: MatchMode | None = None

    def __post_init__(self):
        self.target_column = clean_text(self.target_column)
        self.words = [clean_text(word) for word in self.words]

        if isinstance(self.test_value, list):
            self.test_value = [clean_text(v) if isinstance(v, str) else v for v in self.test_value]
            if self.match_mode is None:
                self.match_mode = MatchMode.ANY
        else:
            if isinstance(self.test_value, str):
                self.test_value = clean_text(self.test_value)

            if self.match_mode is not None:
                warnings.warn(
                    f"RULE '{self.name}': match_mode '{self.match_mode}' ignored. test_values is single item.",
                    stacklevel=2,
                )

            self.match_mode = MatchMode.ANY


RuleConfig = StaticRule | ColumnRule | ConditionalRule


class AppConfig(msgspec.Struct):
    spreadsheet: SpreadsheetConfig
    settings: SettingsConfig
    smtp: SmtpConfig
    filters: list[FilterConfig] = []
    rules: list[RuleConfig] = []


def load_config(path: str) -> AppConfig:
    with open(path, 'rb') as f:
        return msgspec.toml.decode(f.read(), type=AppConfig)
