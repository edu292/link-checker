import contextlib
from asyncio import Semaphore
from collections.abc import Iterable
from io import BytesIO
from itertools import chain

from playwright.async_api import APIRequestContext, BrowserContext, Page, TimeoutError

from config import AppConfig
from shared import Assertion, CompiledCheck, LinkResult, ScrapeTask, Status
from utils import clean_text


def _evaluate_checks(text: str, checks: Iterable[CompiledCheck]) -> tuple[CompiledCheck, str | None] | None:
    for check in checks:
        match = check.pattern.search(text)

        if check.assertion == Assertion.FORBIDDEN and match:
            return check, match.group(0)
        if check.assertion == Assertion.REQUIRED and not match:
            return check, None

    return None


async def scrappe_page(config: AppConfig, page: Page, task: ScrapeTask, checks: Iterable[CompiledCheck]) -> LinkResult:
    try:
        response = await page.goto(task.url, wait_until='load', timeout=config.browser.page_load_timeout)

        if not response:
            return LinkResult(task.url, Status.NETWORK_ERROR)

        status_code = response.status
        if status_code >= 500:
            return LinkResult(task.url, Status.SERVER_ERROR, response.status)
        if status_code == 404:
            return LinkResult(task.url, Status.NOT_FOUND, response.status)
        if status_code >= 400:
            return LinkResult(task.url, Status.CLIENT_ERROR, response.status)

        raw_body = await page.evaluate('window.extractText()')
        body = clean_text(raw_body)

        if not body or len(body) < 200:
            with contextlib.suppress(TimeoutError):
                await page.wait_for_load_state('networkidle', timeout=config.browser.network_idle_timeout)

            raw_body = await page.evaluate('window.extractText()')
            body = clean_text(raw_body)

        if not body:
            return LinkResult(task.url, Status.EMPTY_RESPONSE)
        title = await page.title()
        payload = clean_text(title) + body
        error = _evaluate_checks(payload, checks)
        if error:
            check, match = error
            res = LinkResult(task.url, Status.CONTENT_ERROR, reason=check.error, matched_word=match)
            if check.screenshot:
                await page.wait_for_timeout(config.screenshot.delay)
                await page.evaluate("document.querySelectorAll('svg').forEach(e => e.remove());")
                img = await page.screenshot(
                    type=config.screenshot.format,
                    quality=config.screenshot.quality,
                    full_page=config.screenshot.full_page,
                )
                res.screenshot = img

            return res

        return LinkResult(task.url, Status.OK)
    except TimeoutError:
        return LinkResult(task.url, Status.TIMEOUT)
    except Exception as e:
        return LinkResult(task.url, Status.RUNTIME_ERROR, reason=str(e))


async def process_task(sem: Semaphore, config: AppConfig, context: BrowserContext, task: ScrapeTask, static_checks):
    async with sem:
        page = await context.new_page()
        res = await scrappe_page(config=config, page=page, task=task, checks=chain(static_checks, task.checks))

        await page.close()
        if res.status != Status.OK:
            print(task.row, res)
            return (task.row, res)
        return None


async def get_response_body(context: APIRequestContext, url: str) -> BytesIO:
    response = await context.get(url)
    if not response.ok:
        raise RuntimeError(f'Fetch failed: {response.status}')

    body = await response.body()
    return BytesIO(body)
