import asyncio
import re
import smtplib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from enum import IntEnum, auto
from io import BytesIO

import openpyxl
import requests
from environs import Env
from playwright.async_api import Page, async_playwright

env = Env()
env.read_env()


@dataclass(frozen=True)
class Config:
    SPREADSHEET_URL = env.str('SPREADSHEET_URL')
    SHEET_NAME = env.str('SHEET_NAME', default='')
    LINK_COLUMN_NAME = env.str('LINK_COLUMN_NAME')
    DATE_COLUMN_NAME = env.str('DATE_COLUMN_NAME', default='')
    PAGE_LOAD_TIMEOUT = env.int('PAGE_LOAD_TIMEOUT', default=30000)

    SMTP_HOST = env.str('SMTP_HOST')
    SMTP_PORT = env.int('SMTP_PORT', default=587)
    SMTP_USER = env.str('SMTP_USER', default='')
    SMTP_PASSWORD = env.str('SMTP_PASSWORD', default='')
    EMAIL_FROM = env.str('EMAIL_FROM', default='')
    EMAIL_TO = env.str('EMAIL_TO')


class Status(IntEnum):
    OK = auto()
    ERRO_REDE = auto()
    ERRO_SERVIDOR = auto()
    ERRO_CLIENTE = auto()
    ERRO_EXECUCAO = auto()
    BLOQUEADO_BOT = auto()
    PAGINA_EM_BRANCO = auto()
    PAGINA_MENSAGEM_ERRO = auto()
    PAGINA_MENSAGEM_ESGOTADO = auto()


@dataclass(frozen=True)
class LinkResult:
    url: str
    status: Status
    context: str = ''

    def __str__(self) -> str:
        return f'{self.url} - {self.status.name}: {self.context}'


def get_sheet_links() -> list[tuple[int, str]]:
    url = Config.SPREADSHEET_URL.split('/edit')[0] + '/export?format=xlsx'

    res = requests.get(url)
    res.raise_for_status()

    wb = openpyxl.load_workbook(BytesIO(res.content), data_only=False)
    sheet = None
    if Config.SHEET_NAME:
        try:
            sheet_idx = wb.sheetnames.index(Config.SHEET_NAME)
        except ValueError:
            print(f'Sheet named {Config.SHEET_NAME} does not exst in spreasheet. Defaulting to first active one')
        else:
            sheet = wb.worksheets[sheet_idx]

    if sheet is None:
        sheet = wb.active
    assert sheet is not None

    link_col_idx = None
    date_col_idx = None
    for link_cell in sheet[1]:
        match link_cell.value:
            case Config.LINK_COLUMN_NAME:
                link_col_idx = link_cell.column
            case Config.DATE_COLUMN_NAME:
                date_col_idx = link_cell.column

    if not link_col_idx:
        raise ValueError(f'Link column {Config.LINK_COLUMN_NAME} not found')
    if Config.DATE_COLUMN_NAME and not date_col_idx:
        raise ValueError(f'Date column {Config.DATE_COLUMN_NAME} not found')

    links = []
    for row in range(2, sheet.max_row + 1):
        if date_col_idx:
            date_cell = sheet.cell(row=row, column=date_col_idx)
            date = date_cell.value

            if not (isinstance(date, datetime) and date > datetime.now()):
                continue

        link_cell = sheet.cell(row=row, column=link_col_idx)
        if link_cell.hyperlink and link_cell.hyperlink.target:
            links.append((row, link_cell.hyperlink.target))

    return links


def clean_text(text: str) -> str:
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('utf-8')
    text = re.sub(r'\s+', ' ', text)
    return text.lower().strip()


async def get_text(page) -> str:
    script = r"""
    (el) => {
        return new Promise((resolve) => {
            let attempts = 0;

            function extractText() {
                let text = '';
                function walk(node) {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        const tag = node.tagName.toUpperCase();
                        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') return;
                    }
                    if (node.nodeType === Node.TEXT_NODE) {
                        text += node.nodeValue + ' ';
                    }
                    if (node.shadowRoot) {
                        for (let child of node.shadowRoot.childNodes) walk(child);
                    }
                    for (let child of node.childNodes) walk(child);
                }
                walk(el);
                return text.replace(/\s+/g, ' ').trim();
            }

            const timer = setInterval(() => {
                attempts++;
                const txt = extractText();
                if (txt.length > 20 || attempts >= 40) {
                    clearInterval(timer);
                    resolve(txt);
                }
            }, 500);
        });
    }
    """
    body = await page.locator('body').element_handle()
    if not body:
        return ''
    return await body.evaluate(script)


async def check_link(page: Page, url: str) -> LinkResult:
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=Config.PAGE_LOAD_TIMEOUT)

        if not response:
            return LinkResult(url, Status.ERRO_REDE)

        if response.status >= 500:
            return LinkResult(url, Status.ERRO_SERVIDOR)
        if response.status >= 400:
            return LinkResult(url, Status.ERRO_CLIENTE)

        raw_text = await get_text(page)
        texto_corpo = clean_text(raw_text)

        if not texto_corpo:
            return LinkResult(url, Status.PAGINA_EM_BRANCO)

        titulo = clean_text(await page.title())

        palavras_erro = ['not found', 'nao encontrada', 'nao encontrado', 'erro', 'manutencao', 'offline']
        has_error_word = any(k in titulo or k in texto_corpo for k in palavras_erro)
        has_404 = re.search(r'\b404\b', titulo) or re.search(r'\b404\b', texto_corpo)

        if has_error_word or has_404:
            return LinkResult(url, Status.PAGINA_MENSAGEM_ERRO)

        palavras_bot = [
            'cloudflare',
            'captcha',
            'attention required',
            'checking your browser',
            'robot',
            'sou humano',
            'permission',
        ]
        if any(k in titulo or k in texto_corpo for k in palavras_bot):
            print(texto_corpo)
            return LinkResult(url, Status.BLOQUEADO_BOT)

        palavras_esgotado = ['esgotado', 'indisponivel', 'nao ha ingressos', 'encerrado']
        palavras_ativo = ['comprar', 'ingresso', 'selecionar assento', 'checkout', 'entrada']

        if any(k in texto_corpo for k in palavras_esgotado) and not any(k in texto_corpo for k in palavras_ativo):
            return LinkResult(url, Status.PAGINA_MENSAGEM_ESGOTADO)

        return LinkResult(url, Status.OK)

    except Exception as e:
        return LinkResult(url, Status.ERRO_EXECUCAO, str(e))


async def process_row(sem: asyncio.Semaphore, context, row, link):
    async with sem:
        page = await context.new_page()
        res = await check_link(page, link)
        await page.close()

        if res.status != Status.OK:
            print(row, res)
            return (row, res)
        return None


def send_error_report(failures: list[tuple[int, LinkResult]], total_links: int):
    if not Config.SMTP_HOST or not Config.EMAIL_TO:
        print('SMTP config missing')
        return

    fail_count = len(failures)

    msg = EmailMessage()
    msg['Subject'] = f'[{fail_count}/{total_links} Falhas] Monitoramento de Links'
    email_from = Config.EMAIL_FROM if Config.EMAIL_FROM else Config.SMTP_USER
    msg['From'] = email_from
    msg['To'] = Config.EMAIL_TO
    body = ''
    for row, res in failures:
        body += f'\n[Linha {row:03d}] {res.status.name}'
        body += f'\nURL:    {res.url}'
        if res.context:
            body += f'\nMotivo: {res.context}\n'

    msg.set_content(body)

    try:
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.send_message(msg)
        print('Email enviado.')
    except Exception as e:
        print(f'Erro SMTP: {e!s}')


async def main():
    links = get_sheet_links()
    total_links = len(links)
    if total_links == 0:
        return

    sem = asyncio.Semaphore(10)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            extra_http_headers={'sec-ch-ua': '"Chromium";v="125", "Not.A/Brand";v="24"'},
        )

        tasks = [process_row(sem, context, row, url) for row, url in links]
        results = await asyncio.gather(*tasks)

        await browser.close()
    failures = [r for r in results if r is not None]

    if failures:
        send_error_report(failures, total_links)
    else:
        print(f'Sucesso. {total_links} links checados. Zero falhas.')


if __name__ == '__main__':
    asyncio.run(main())
