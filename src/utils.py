import operator
import re
import unicodedata
from enum import StrEnum

RE_SPACES = re.compile(r'\s+')


class OperatorType(StrEnum):
    LT = '<'
    GT = '>'
    LE = '<='
    GE = '>='
    EQ = '=='
    NE = '!='


OPERATOR_MAP = {
    OperatorType.LT: operator.lt,
    OperatorType.GT: operator.gt,
    OperatorType.LE: operator.le,
    OperatorType.GE: operator.ge,
    OperatorType.EQ: operator.eq,
    OperatorType.NE: operator.ne,
}


def clean_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    text = RE_SPACES.sub(' ', text)
    return text.lower().strip()
