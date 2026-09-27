"""User-driven Edge login for pages that cannot be read anonymously."""

from pathlib import Path
import threading
from urllib.parse import urlsplit

from opti_core import DATA
from opti_web import AuthenticationRequired, _public_target, format_webpage


PROFILE_DIR = DATA / 'web-browser'
MAX_BROWSER_HTML = 2 * 1024 * 1024


def _guard_request(route):
    """Prevent a public page's scripts from reaching local or private services."""
    url = route.request.url
    if urlsplit(url).scheme in ('data', 'blob'):
        route.continue_()
        return
    try:
        _public_target(url)
    except ValueError:
        route.abort()
    else:
        route.continue_()


def _guard_websocket(route):
    url = route.url
    scheme = urlsplit(url).scheme
    try:
        if scheme not in ('ws', 'wss'):
            raise ValueError('Unsupported WebSocket URL')
        _public_target(('https' if scheme == 'wss' else 'http') + url[len(scheme):])
    except ValueError:
        route.close()
    else:
        route.connect_to_server()


def _navigate(page, url, page_number, page_count):
    response = page.goto(url, wait_until='domcontentloaded', timeout=20000)
    page.wait_for_timeout(900)
    _public_target(page.url)
    if response is not None and response.status in (401, 403):
        raise AuthenticationRequired(f'網頁要求登入或授權（HTTP {response.status}）。')
    if page.locator('input[type="password"]:visible').count():
        raise AuthenticationRequired('此網頁顯示登入表單，請先登入再讀取。')
    html = page.content()
    if len(html) > MAX_BROWSER_HTML:
        raise ValueError('登入後網頁超過 2 MB 解析上限。')
    return format_webpage(page.url, html, 'text/html', page_number, page_count)


def read_authenticated(url, page=1, page_count=1, confirm=None, cancelled=None):
    """Reuse an isolated Edge profile; show Edge only when fresh sign-in is needed."""
    _public_target(url)
    cancelled = cancelled or threading.Event()
    if cancelled.is_set():
        raise ValueError('已取消網頁讀取。')
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise ValueError('登入網頁功能尚未安裝完成；請重新啟動 OptiChat 套用更新。') from error
    Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as playwright:
            for headless in (True, False):
                context = playwright.chromium.launch_persistent_context(
                    str(PROFILE_DIR), channel='msedge', headless=headless,
                    accept_downloads=False, service_workers='block')
                try:
                    context.route('**/*', _guard_request)
                    context.route_web_socket('**/*', _guard_websocket)
                    tab = context.new_page()
                    try:
                        result = _navigate(tab, url, page, page_count)
                    except AuthenticationRequired:
                        if headless:
                            continue
                        for _attempt in range(2):
                            if cancelled.is_set():
                                raise ValueError('已取消網頁讀取。')
                            if confirm is None or not confirm(url, cancelled):
                                raise ValueError('已取消登入，網頁未讀取。')
                            if cancelled.is_set():
                                raise ValueError('已取消網頁讀取。')
                            try:
                                return _navigate(tab, url, page, page_count)
                            except AuthenticationRequired:
                                continue
                        raise ValueError('登入後仍無法讀取此網頁；請確認帳號權限或稍後重試。')
                    else:
                        tab.close()
                        return result
                finally:
                    context.close()
    except PlaywrightError as error:
        raise ValueError('無法啟動 Microsoft Edge 讀取登入網頁：' + str(error)) from error


__all__ = ['read_authenticated']
