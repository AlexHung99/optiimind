"""Regression checks for public webpage reading without external network access."""

import queue
import socket
import threading
import unittest
from unittest.mock import patch

import opti_agent
import opti_app
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


if __name__ == '__main__':
    unittest.main()
