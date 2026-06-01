import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from enum import IntEnum, auto
from urllib.parse import urlparse

from playwright.async_api import BrowserContext, Page, TimeoutError, async_playwright

from utils import clean_text


class Status(IntEnum):
    OK = auto()
    ERRO_REDE = auto()
    ERRO_SERVIDOR = auto()
    PAGINA_NAO_ENCONTRADA = auto()
    ERRO_CLIENTE = auto()
    ERRO_EXECUCAO = auto()
    TIMEOUT = auto()
    PAGINA_EM_BRANCO = auto()


@dataclass(slots=True)
class LinkResult:
    url: str
    status: Status
    reason: str = ''
    screenshot: bytes | None = None

    def __str__(self) -> str:
        return f'{self.url} - {self.status.name}\n {self.reason}'


BLOCKED_RESOURCE_TYPES = {
    'image',
    'stylesheet',
    'media',
    'font',
    'other',
    'manifest',
    'websocket',
    'eventsource',
    'ping',
    'csp_report',
}
SAME_ORIGIN_ONLY_RESOURCE_TYPES = {
    'script',
    'fetch',
    'xhr',
}
EXTRACT_TEXT_JS = (BASE_DIR / 'extract_text.js').read_text()


async def get_text(page: Page) -> str:
    try:
        return await page.evaluate('window.extractText()')
    except Exception:
        return ''


def apply_rules(text: str, rules: list) -> str | None:
    for rule in rules:
        found = bool(rule.pattern.search(text))

        if rule.type == RuleType.FORBIDDEN and found:
            return rule.name
        if rule.type == RuleType.REQUIRED and not found:
            return rule.name

    return None


async def check_link(page: Page, url: str) -> LinkResult:
    try:
        response = await page.goto(url, wait_until='domcontentloaded', timeout=config.settings.page_load_timeout)

        if not response:
            return LinkResult(url, Status.ERRO_REDE)

        if response.status >= 500:
            return LinkResult(url, Status.ERRO_SERVIDOR)
        if response.status == 404:
            return LinkResult(url, Status.PAGINA_NAO_ENCONTRADA)
        if response.status >= 400:
            return LinkResult(url, Status.ERRO_CLIENTE)

        titulo = clean_text(await page.title())
        match = apply_rules(titulo)
        if match:
            return LinkResult(url, match)

        raw_text = await get_text(page)
        texto_corpo = clean_text(raw_text)

        if not texto_corpo:
            try:
                await page.wait_for_load_state('networkidle', timeout=config.settings.network_idle_timeout)
            except TimeoutError:
                return LinkResult(url, Status.TIMEOUT)
            raw_text = await get_text(page)
            texto_corpo = clean_text(raw_text)

        if not texto_corpo:
            return LinkResult(url, Status.PAGINA_EM_BRANCO)

        match = apply_rules(texto_corpo)
        if match:
            return LinkResult(url)

        return LinkResult(url, Status.OK)
    except TimeoutError:
        return LinkResult(url, Status.TIMEOUT)
    except Exception as e:
        return LinkResult(url, Status.ERRO_EXECUCAO, str(e))


def get_root_domain(url):
    netloc = urlparse(url).netloc.split(':')[0]
    return next((p for p in reversed(netloc.split('.')) if len(p) > 3), netloc)


async def process_row(sem: asyncio.Semaphore, context: BrowserContext, row, link):
    async with sem:
        page = await context.new_page()
        res = await check_link(page, link)
        if Config.TAKE_SCREENSHOTS and res.status in SCREENSHOT_STATUSES:
            try:
                await page.wait_for_timeout(Config.UI_SETTLE_DELAY)
                await page.evaluate("document.querySelectorAll('svg').forEach(e => e.remove());")
                img = await page.screenshot(type='jpeg', quality=50, full_page=True)
                res.screenshot = img
            except Exception:
                pass

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
        if res.reason:
            body += f'\nMotivo: {res.reason}\n'

    msg.set_content(body)
    for row, res in failures:
        if res.screenshot:
            msg.add_attachment(
                res.screenshot, maintype='image', subtype='jpeg', filename=f'{res.status.name}_{row}.jpeg'
            )

    try:
        with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT) as server:
            server.starttls()
            server.login(Config.SMTP_USER, Config.SMTP_PASSWORD)
            server.send_message(msg)
        print('Email enviado.')
    except Exception as e:
        print(f'Erro SMTP: {e!s}')


async def main():
    sem = asyncio.Semaphore(Config.MAX_CONCURRENT_PAGES)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--headless=new',
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--disable-extensions',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-gl-drawing-for-tests',
                '--disable-animations',
                '--blink-settings=imagesEnabled=false',
                '--mute-audio',
                '--hide-scrollbars',
                '--disable-site-isolation-trials',
                '--disable-webgl',
                '--disable-background-networking',
                '--single-process',
                '--disable-sync',
                '--disable-translate',
                '--no-first-run',
                '--disable-default-apps',
                '--metrics-recording-only',
                '--safebrowsing-disable-auto-update',
                '--disable-background-timer-throttling',
                '--disable-backgrounding-occluded-windows',
                '--disable-renderer-backgrounding',
                '--disable-ipc-flooding-protection',
                '--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider',
            ],
        )
        context = await browser.new_context(
            ignore_https_errors=True,
            has_touch=False,
            service_workers='block',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
            extra_http_headers={'sec-ch-ua': '"Chromium";v="125", "Not.A/Brand";v="24"'},
        )
        links = await get_sheet_data(context.request)
        total_links = len(links)
        if total_links == 0:
            print('Nenhum link foi encontrado')
            return

        await context.add_init_script(EXTRACT_TEXT_JS)
        await context.route(
            '**/*',
            lambda route: (
                route.abort()
                if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                or (
                    route.request.resource_type in SAME_ORIGIN_ONLY_RESOURCE_TYPES
                    and get_root_domain(route.request.url) != get_root_domain(route.request.frame.url)
                )
                else route.continue_()
            ),
        )

        tasks = [process_row(sem, context, row, url) for row, url in links]
        results = await asyncio.gather(*tasks)

        await browser.close()
    failures = [r for r in results if r is not None]

    if failures:
        print(f'Foram encontrados {len(failures)}/{total_links} links com erro')
        if config.settings.send_email:
            send_error_report(failures, total_links)
    else:
        print(f'Sucesso. {total_links} links checados. Zero falhas.')


if __name__ == '__main__':
    asyncio.run(main())
