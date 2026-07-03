import re
import unicodedata
from datetime import datetime
from urllib.parse import urlparse

RE_SPACES = re.compile(r'\s+')


def clean_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    text = RE_SPACES.sub(' ', text)
    return text.lower().strip()


def get_root_domain(url: str) -> str:
    netloc = urlparse(url).netloc.split(':')[0]
    return next((p for p in reversed(netloc.split('.')) if len(p) > 3), netloc)


def build_datetime_regexes(dt: datetime) -> list[str]:
    months = [
        'janeiro',
        'fevereiro',
        'marco',
        'abril',
        'maio',
        'junho',
        'julho',
        'agosto',
        'setembro',
        'outubro',
        'novembro',
        'dezembro',
    ]

    day = rf'0?{dt.day}'
    month_num = rf'0?{dt.month}'

    month_long = months[dt.month - 1]
    month_abreviation = month_long[:3]
    month_name = rf'(?:{month_long}|{month_abreviation})'

    y = rf'(?:\s+(?:de\s+)?(?:{dt.year}|{dt.year % 100:02d}))?'

    p1 = rf'{day}\s+de\s+{month_name}{y}'
    p2 = rf'{day}\D+{month_num}{y}'
    p3 = rf'{day}\s+{month_name}{y}'

    return [p1, p2, p3]
