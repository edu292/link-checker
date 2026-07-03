import asyncio
import smtplib
from email.message import EmailMessage
from enum import IntEnum, auto
from pathlib import Path

from playwright.async_api import Route, async_playwright

from config import AppConfig, MatchColumnCheck, MatchTextCheck, load_config
from parser import get_scrapper_tasks
from scrapper import get_response_body, process_task
from shared import CompiledCheck, LinkResult
from utils import get_root_domain

BASE_DIR = Path(__file__).parent

BLOCKED_RESOURCE_TYPES = {
    'image',
    'texttrack',
    'media',
    'font',
    'other',
    'manifest',
    'websocket',
    'eventsource',
    'ping',
    'csp_report',
}

SAME_ORIGIN_RESOURCE_TYPES = {'script', 'xhr', 'fetch'}


class Status(IntEnum):
    OK = auto()
    NETWORK_ERROR = auto()
    NOT_FOUND = auto()
    CLIENT_ERROR = auto()
    RUNTIME_ERROR = auto()
    TIMEOUT = auto()
    EMPTY_RESPONSE = auto()


def send_error_report(config: AppConfig, failures: list[tuple[int, LinkResult]], total_links: int):
    if not config.smtp.host or not config.smtp.to_addresses:
        raise RuntimeError('Missing required smtp settings: host, to_addresses')

    fail_count = len(failures)
    msg = EmailMessage()
    msg['Subject'] = f'[{fail_count}/{total_links} Falhas] Monitoramento de Links'
    email_from = config.smtp.from_address if config.smtp.from_address else config.smtp.user
    msg['From'] = email_from
    msg['To'] = config.smtp.to_addresses
    body = ''
    for row, res in failures:
        body += f'\n[Row {row:03d}] {res.status.name}'
        body += f'\nURL:    {res.url}'
        if res.http_code:
            body += f'\nHTTP:   {res.http_code}'
        if res.reason:
            body += f'\nReason: {res.reason}'
        if res.matched_word:
            body += f'\nMatch:  "{res.matched_word}"'
        body += '\n'

    msg.set_content(body)
    for row, res in failures:
        if res.screenshot:
            msg.add_attachment(
                res.screenshot,
                maintype='image',
                subtype=config.screenshot.format,
                filename=f'{res.reason if res.reason else res.status.name}_{row}.{config.screenshot.format}',
            )

    with smtplib.SMTP(config.smtp.host, config.smtp.port) as server:
        server.starttls()
        server.login(config.smtp.user, config.smtp.password)
        server.send_message(msg)
    print('email sent')


async def _handle_route(route: Route):
    request = route.request
    resource_type = request.resource_type
    url = request.url

    if resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return

    if resource_type == 'stylesheet':
        await route.fulfill(status=200, content_type='text/css', body='')
        return

    if resource_type in SAME_ORIGIN_RESOURCE_TYPES and get_root_domain(url) != get_root_domain(request.frame.url):
        await route.fulfill(status=200, content_type='application/javascript', body='')
        return

    await route.continue_()


async def main(config: AppConfig):
    sem = asyncio.Semaphore(config.browser.max_concurrent_pages)
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
        await context.add_init_script(path=BASE_DIR / 'extract_text.js')
        await context.route(
            '**/*',
            _handle_route,
        )

        spreadsheet_bytes = await get_response_body(context.request, config.spreadsheet.url)
        static_checks = []
        checks_to_compile = []
        for check in config.checks:
            match check:
                case MatchColumnCheck():
                    checks_to_compile.append(check)
                case MatchTextCheck():
                    if check.is_conditional:
                        checks_to_compile.append(check)
                    else:
                        static_checks.append(
                            CompiledCheck(
                                error=check.error,
                                targets=check.text,  # pyright: ignore[reportArgumentType]
                                assertion=check.assertion,  # pyright: ignore[reportArgumentType]
                                screenshot=check.screenshot,
                            )
                        )

        tasks = get_scrapper_tasks(
            bytes=spreadsheet_bytes,
            sheetname=config.spreadsheet.sheet,
            link_column=config.spreadsheet.link_column,
            filters=config.filters,
            checks_to_compile=checks_to_compile,
        )

        total_tasks = len(tasks)
        if total_tasks == 0:
            print('no links found')
            return

        tasks = [
            process_task(sem=sem, config=config, context=context, task=task, static_checks=static_checks)
            for task in tasks
        ]

        results = await asyncio.gather(*tasks)
    failures = [r for r in results if r is not None]

    if failures:
        print(f'{len(failures)}/{total_tasks} errors encountered')
        if config.smtp.enabled:
            send_error_report(config, failures, total_tasks)
    else:
        print(f'{total_tasks} links scrapped. No erros')


if __name__ == '__main__':
    config = load_config(BASE_DIR / 'config.toml')
    asyncio.run(main(config))
