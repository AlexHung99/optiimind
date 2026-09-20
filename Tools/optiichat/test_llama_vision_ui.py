import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
import llama_vision_ui as ui


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        if self.server.chunked:
            self.send_header('Transfer-Encoding', 'chunked')
        self.end_headers()
        self.wfile.flush()
        self.server.started.set()
        if self.server.slow:
            self.server.release.wait(5)
        events = [{'message': {'content': '紅色'}}, {'message': {'content': '方形'}}, {'done': True}]
        if self.server.truncated:
            events = events[:1]
        try:
            if self.server.chunked:
                payload = b''.join((json.dumps(event, ensure_ascii=False)+'\n').encode('utf-8') for event in events)
                for offset in range(0, len(payload), 7):
                    part = payload[offset:offset+7]
                    self.wfile.write(f'{len(part):x}\r\n'.encode('ascii')+part+b'\r\n')
                self.wfile.write(b'0\r\n\r\n')
                self.wfile.flush()
                return
            for event in events:
                self.wfile.write((json.dumps(event, ensure_ascii=False)+'\n').encode('utf-8'))
                self.wfile.flush()
        except (OSError, ConnectionError):
            pass


class ChatIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.slow = False
        self.server.truncated = False
        self.server.chunked = False
        self.server.started = threading.Event()
        self.server.release = threading.Event()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host_patch = patch.object(ui, 'HOST', f'127.0.0.1:{self.server.server_port}')
        self.host_patch.start()

    def tearDown(self):
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.host_patch.stop()

    def test_image_and_unicode_stream_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'測試.png'
            Image.new('RGBA', (1200, 800), (255, 0, 0, 255)).save(path)
            encoded, _ = ui.prepare_image(path)
            decoded = Image.open(io.BytesIO(base64.b64decode(encoded)))
            self.assertEqual(decoded.width, 560)
            events = []
            pending = {'role': 'user', 'content': '這是什麼？', 'images': [encoded]}
            ui.StreamRequest().stream(ui.build_messages([], pending), lambda *event: events.append(event))
            self.assertEqual(''.join(value for kind, value in events if kind == 'token'), '紅色方形')
            self.assertEqual(events[-1][0], 'complete')
            self.assertEqual(self.server.payload['messages'][-1]['images'], [encoded])
            self.assertEqual(self.server.payload['messages'][-1]['content'], '這是什麼？')

    def test_disconnect_does_not_count_as_completed_answer(self):
        self.server.truncated = True
        with self.assertRaisesRegex(RuntimeError, '連線提早結束'):
            ui.StreamRequest().stream([], lambda *event: None)

    def test_chunked_response_split_inside_unicode_characters(self):
        self.server.chunked = True
        events = []
        ui.StreamRequest().stream([], lambda *event: events.append(event))
        self.assertEqual(''.join(value for kind, value in events if kind == 'token'), '紅色方形')
        self.assertEqual(events[-1][0], 'complete')

    def test_cancel_interrupts_wait_for_first_token(self):
        self.server.slow = True
        request = ui.StreamRequest()
        def run():
            try:
                request.stream([], lambda *event: None)
            except (OSError, http.client.HTTPException):
                pass
        import http.client
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        self.assertTrue(self.server.started.wait(2))
        request.cancel()
        worker.join(2)
        self.assertFalse(worker.is_alive(), 'Stop must unblock the socket promptly')

    def test_new_image_replaces_old_image_without_mutating_history(self):
        history = [{'role': 'user', 'content': 'old', 'images': ['old-image']},
                   {'role': 'assistant', 'content': 'answer'}]
        messages = ui.build_messages(history, {'role': 'user', 'content': 'new', 'images': ['new-image']})
        self.assertEqual(sum(bool(m.get('images')) for m in messages), 1)
        self.assertEqual(history[0]['images'], ['old-image'])

    def test_widget_image_send_reply_and_new_conversation(self):
        with patch.object(ui, 'ensure_service', return_value={}):
            root = ui.tk.Tk()
            root.withdraw()
            app = ui.ChatApp(root)
            try:
                deadline = time.monotonic()+4
                while not app.ready and time.monotonic() < deadline:
                    root.update()
                    time.sleep(.02)
                self.assertTrue(app.ready)
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp)/'photo.jpg'
                    Image.new('RGB', (100, 100), 'red').save(path)
                    app.attach_image(path)
                    self.assertEqual(app.pending_path, path)
                    app.input.insert('1.0', '辨識圖片')
                    app.send()
                    deadline = time.monotonic()+5
                    while app.busy and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.02)
                    self.assertFalse(app.busy)
                    self.assertEqual(app.last_answer, '紅色方形')
                    self.assertEqual(len(app.history), 2)
                    self.assertIn('紅色方形', app.transcript.get('1.0', 'end'))
                    app.new_chat()
                    self.assertEqual(app.history, [])
                    self.assertIsNone(app.pending_path)
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
