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
    months_pt = {
        1: ('janeiro', 'jan'),
        2: ('fevereiro', 'fev'),
        3: ('marco', 'mar'),
        4: ('abril', 'abr'),
        5: ('maio', 'mai'),
        6: ('junho', 'jun'),
        7: ('julho', 'jul'),
        8: ('agosto', 'ago'),
        9: ('setembro', 'set'),
        10: ('outubro', 'out'),
        11: ('novembro', 'nov'),
        12: ('dezembro', 'dez'),
    }

    d = rf'0?{dt.day}'
    m_num = rf'0?{dt.month}'
    m_long, m_short = months_pt[dt.month]
    m_text = rf'(?:{m_long}|{m_short})'

    y = rf'(?:\s+(?:de\s+)?(?:{dt.year}|{dt.year % 100:02d}))'

    p1 = rf'{d}\s+de\s+{m_text}{y}?'
    p2 = rf'{d}\D+{m_num}{y}?'

    p3 = rf'{d}\s+{m_text}{y}?'

    return [p1, p2, p3]
