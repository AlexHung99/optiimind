"""Regression checks for public webpage reading without external network access."""

import queue
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

import opti_agent
import opti_app
import opti_browser
import opti_web


class WebReaderTests(unittest.TestCase):
    def test_extract_urls_from_chinese_prose(self):
        self.assertEqual(opti_web.extract_urls('請分析 https://example.org/a?x=1，以及 http://example.net/b。'),
                         ['https://example.org/a?x=1', 'http://example.net/b'])

    def test_private_and_non_http_targets_are_rejected(self):
        with patch.object(socket, 'getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]):
            with self.assertRaisesRegex(ValueError, '私人網路'):
                opti_web._public_target('http://localhost/admin')
        for url in ('file:///C:/secret', 'http://example.com:8080/', 'https://user:pass@example.com/'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                opti_web._public_target(url)

    def test_redirect_to_private_host_is_blocked(self):
        class Response:
            status = 302

            def getheader(self, name, default=None):
                return 'http://localhost/private' if name == 'Location' else default

        class Connection:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        def addresses(host, port, **kwargs):
            ip = '127.0.0.1' if host == 'localhost' else '93.184.215.14'
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, port))]

        with patch.object(socket, 'getaddrinfo', side_effect=addresses), \
                patch.object(opti_web.http.client, 'HTTPSConnection', Connection):
            with self.assertRaisesRegex(ValueError, '私人網路'):
                opti_web._download('https://example.org/article')

    def test_html_extracts_main_without_navigation_or_scripts(self):
        html = ("<html><head><title>交通公告</title><meta name='description' content='最新公告'></head>"
                "<body><nav><img src='logo.png'><a>選單</a></nav><main><h1>停車資訊</h1>"
                "<p>第一段內容，這裡有很多詳細資訊。</p><p>第二段內容，包含費率和時間。</p>"
                "<script>ignore me</script></main><footer>頁尾</footer></body></html>")
        with patch.object(opti_web, '_download', return_value=('https://example.org/a', html, 'text/html')):
            result = opti_web.fetch_webpage('https://example.org/a')
        self.assertIn('標題：交通公告', result)
        self.assertIn('停車資訊', result)
        self.assertNotIn('選單', result)
        self.assertNotIn('ignore me', result)
        self.assertNotIn('頁尾', result)

    def test_login_page_requires_user_authentication(self):
        html = '<html><main><h1>登入</h1><form><input name="pw" type="password"></form></main></html>'
        with patch.object(opti_web, '_download', return_value=('https://example.org/login', html, 'text/html')):
            with self.assertRaises(opti_web.AuthenticationRequired):
                opti_web.fetch_webpage('https://example.org/private')

    def test_http_unauthorized_requests_sign_in(self):
        class Response:
            status = 401

        class Connection:
            def __init__(self, *args, **kwargs):
                pass

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with patch.object(opti_web, '_public_target', return_value=(
                'https://example.org/private', 'example.org', 443, '93.184.215.14')), \
                patch.object(opti_web.http.client, 'HTTPSConnection', Connection):
            with self.assertRaises(opti_web.AuthenticationRequired):
                opti_web.fetch_webpage('https://example.org/private')

    def test_agent_uses_login_callback_after_authentication_error(self):
        answers = iter(['{"action":"read_webpage","url":"https://example.org/private"}',
                        '{"action":"finish","answer":"已讀取會員頁面。"}'])
        events, login_calls = [], []

        def login(url, page, cancelled):
            login_calls.append((url, page, cancelled.is_set()))
            return '來源：https://example.org/private\n會員頁面正文'

        runner = opti_agent.AgentRunner('', lambda _messages, _cancel: next(answers),
            lambda event, value: events.append((event, value)), web_login=login)
        with patch.object(opti_agent, 'fetch_webpage', side_effect=opti_web.AuthenticationRequired('login')):
            self.assertEqual(runner.run('分析會員頁面'), '已讀取會員頁面。')
        self.assertEqual(login_calls, [('https://example.org/private', 1, False)])
        self.assertIn('會員頁面正文', next(v for k, v in events if k == 'step')['result'])

    def test_browser_route_blocks_private_requests(self):
        class Route:
            def __init__(self, url):
                self.request = type('Request', (), {'url': url})()
                self.action = None

            def abort(self):
                self.action = 'blocked'

            def continue_(self):
                self.action = 'allowed'

        with patch.object(opti_browser, '_public_target', side_effect=ValueError('private')):
            route = Route('http://127.0.0.1/private')
            opti_browser._guard_request(route)
            self.assertEqual(route.action, 'blocked')

    def test_browser_waits_for_user_login_then_retries_original_url(self):
        contexts = [MagicMock(), MagicMock()]
        chromium = MagicMock()
        chromium.launch_persistent_context.side_effect = contexts
        playwright = MagicMock()
        playwright.chromium = chromium
        manager = MagicMock()
        manager.__enter__.return_value = playwright
        api = types.ModuleType('playwright.sync_api')
        api.Error = RuntimeError
        api.sync_playwright = lambda: manager
        package = types.ModuleType('playwright')
        package.sync_api = api
        approvals = []

        def confirm(url, cancelled):
            approvals.append(url)
            return True

        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(sys.modules, {'playwright': package, 'playwright.sync_api': api}), \
                patch.object(opti_browser, 'PROFILE_DIR', Path(temporary)/'profile'), \
                patch.object(opti_browser, '_public_target'), \
                patch.object(opti_browser, '_navigate', side_effect=[
                    opti_web.AuthenticationRequired('login'),
                    opti_web.AuthenticationRequired('login'),
                    '會員頁面正文']):
            result = opti_browser.read_authenticated('https://example.org/private', confirm=confirm)
        self.assertEqual(result, '會員頁面正文')
        self.assertEqual(approvals, ['https://example.org/private'])
        self.assertEqual([call.kwargs['headless'] for call in
                          chromium.launch_persistent_context.call_args_list], [True, False])
        self.assertEqual([context.close.call_count for context in contexts], [1, 1])

    def test_agent_reads_webpage_without_folder(self):
        answers = iter(['{"action":"read_webpage","url":"https://example.org/a"}',
                        '{"action":"finish","answer":"頁面有停車資訊。"}'])
        events = []
        runner = opti_agent.AgentRunner('', lambda _messages, _cancel: next(answers),
                                        lambda event, value: events.append((event, value)))
        with patch.object(opti_agent, 'fetch_webpage', return_value='標題：交通公告\n停車資訊'):
            self.assertEqual(runner.run('分析 https://example.org/a'), '頁面有停車資訊。')
        step = next(value for event, value in events if event == 'step')
        self.assertEqual(step['url'], 'https://example.org/a')
        self.assertIn('停車資訊', step['result'])

    def test_chat_adds_web_text_to_model_request_without_changing_saved_turn(self):
        class Request:
            kind = 'text'
            device = 'CPU'

            def __init__(self):
                self.cancelled = threading.Event()
                self.sent = None

            def stream(self, messages, callback):
                self.sent = messages

        class App:
            web_urls = ['https://example.org/a']

            def __init__(self):
                self.events = queue.Queue()

        app = App()
        request = Request()
        messages = [{'role': 'system', 'content': '以繁體中文回答。'},
                    {'role': 'user', 'content': '分析 https://example.org/a'}]
        with patch.object(opti_app, 'ensure_model_service'), \
                patch.object(opti_app, 'fetch_webpage', return_value='標題：交通公告\n停車資訊'):
            opti_app.OptiiApp.generate(app, request, messages)
        self.assertIn('停車資訊', request.sent[-1]['content'])
        self.assertIn('待分析資料', request.sent[-1]['content'])
        self.assertEqual(app.events.get(), ('finished', False))

    def test_chat_uses_browser_when_login_is_required(self):
        class Request:
            kind = 'text'
            device = 'CPU'

            def __init__(self):
                self.cancelled = threading.Event()
                self.sent = None

            def stream(self, messages, callback):
                self.sent = messages

        class App:
            web_urls = ['https://example.org/private']

            def __init__(self):
                self.events = queue.Queue()
                self.request_web_login = lambda url, cancelled: True

        app, request = App(), Request()
        messages = [{'role': 'system', 'content': '以繁體中文回答。'},
                    {'role': 'user', 'content': '分析 https://example.org/private'}]
        with patch.object(opti_app, 'ensure_model_service'), \
                patch.object(opti_app, 'fetch_webpage', side_effect=opti_web.AuthenticationRequired('login')), \
                patch.object(opti_browser, 'read_authenticated', return_value='會員頁面正文') as browser:
            opti_app.OptiiApp.generate(app, request, messages)
        self.assertIn('會員頁面正文', request.sent[-1]['content'])
        browser.assert_called_once()


if __name__ == '__main__':
    unittest.main()
