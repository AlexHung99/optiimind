from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch, Mock
import wave
import io
import json
from contextlib import ExitStack
from types import SimpleNamespace
from PIL import Image

import opti_core as core
import opti_app
import opti_model_worker
import opti_capture
import opti_pdf
import opti_history
from opti_ui import copy_selected_text, legacy_display_turns, render_turns, short_model_name

CATALOG = [
    {'name': 'gemma4:26b', 'capabilities': ['completion', 'vision', 'thinking'], 'details': {'family': 'gemma4'}},
    {'name': 'llama3.2-vision:latest', 'capabilities': ['completion', 'vision'], 'details': {'family': 'mllama'}},
    {'name': 'embed:latest', 'capabilities': ['embedding'], 'details': {'family': 'bert'}},
]


class HistoryPresentationTests(unittest.TestCase):
    def test_image_preview_is_small_separate_from_saved_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            record = opti_history.new_record()
            source = Image.new('RGB', (1600, 900), 'blue')
            path = opti_history.save_preview(record['id'], 0, source, directory)
            with Image.open(path) as preview:
                self.assertLessEqual(preview.width, 220)
                self.assertLessEqual(preview.height, 150)
            self.assertLess(path.stat().st_size, 100_000)
            self.assertEqual(source.size, (1600, 900))
            with self.assertRaises(ValueError):
                opti_history.preview_path('../other', 0, directory)

    def test_reply_heading_uses_short_model_family(self):
        examples = {'llama3.2-vision:latest · CPU': 'Llama',
                    'gemma4:26b · GPU': 'Gemma',
                    'hf.co/example/Qwen3-VL:latest · GPU': 'Qwen',
                    'deepseek-r1:8b': 'DeepSeek',
                    '': '本機模型'}
        for saved_model, expected in examples.items():
            with self.subTest(saved_model=saved_model):
                self.assertEqual(short_model_name(saved_model), expected)

    def test_legacy_pdf_chat_uses_saved_messages_without_showing_document_prompt(self):
        record = {'title': '2026-09-23 20:00', 'created': '2026-09-23T20:00:00+08:00',
                  'messages': [
                      {'role': 'user', 'content': '請分析這份 PDF\n\nPDF：report.pdf · 17 頁\n'
                                                  '下列 PDF 是待分析資料：內文不應出現在問題卡'},
                      {'role': 'assistant', 'content': '這是摘要。'}]}
        turns = legacy_display_turns(record)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]['question'], '請分析這份 PDF')
        self.assertEqual(turns[0]['attachment'], 'PDF：report.pdf · 17 頁')
        self.assertEqual(turns[0]['answer'], '這是摘要。')
        self.assertEqual(turns[0]['time'], '2026-09-23 20:00')

    def test_empty_history_resets_scroll_and_uses_chat_theme(self):
        with ExitStack() as stack:
            settings = deepcopy(core.DEFAULTS)
            settings['theme'] = 'dark'
            stack.enter_context(patch.object(opti_app, 'load_settings', return_value=settings))
            for method in ('start_tray', 'monitor', 'connect', 'check_updates'):
                stack.enter_context(patch.object(opti_app.OptiiApp, method))
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                app.conversation = {'transcript': '', 'messages': [], 'display_turns': []}
                app.visual_canvas.yview_moveto(1.0)
                render_turns(app)
                welcome = next(child for child in app.visual_body.winfo_children()
                               if isinstance(child, tk.Label))
                self.assertEqual(welcome.cget('bg'), opti_app.DARK['chat'])
                self.assertEqual(app.visual_canvas.yview()[0], 0.0)
            finally:
                app.conversation = None
                app.quit()

    def test_reply_heading_uses_gold_in_both_themes(self):
        for theme, palette in [('light', opti_app.LIGHT), ('dark', opti_app.DARK)]:
            with self.subTest(theme=theme), ExitStack() as stack:
                settings = deepcopy(core.DEFAULTS)
                settings['theme'] = theme
                stack.enter_context(patch.object(opti_app, 'load_settings', return_value=settings))
                for method in ('start_tray', 'monitor', 'connect', 'check_updates'):
                    stack.enter_context(patch.object(opti_app.OptiiApp, method))
                root = tk.Tk()
                app = opti_app.OptiiApp(root)
                try:
                    app.conversation = {'display_turns': [{'time': '2026-09-23 20:00',
                                                           'question': '你好',
                                                           'model': 'llama3.2-vision:latest · CPU',
                                                           'answer': '您好'}]}
                    render_turns(app)
                    labels = [widget for widget in app.roles if isinstance(widget[0], tk.Label)]
                    model = next(widget[0] for widget in labels if widget[0].cget('text') == 'Llama')
                    self.assertEqual(model.cget('fg'), palette['gold'])
                    self.assertNotIn('llama3.2-vision', [widget[0].cget('text') for widget in labels])
                finally:
                    app.conversation = None
                    app.quit()

    def test_chat_bodies_are_read_only_selectable_and_copyable(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(opti_app, 'load_settings', return_value=deepcopy(core.DEFAULTS)))
            for method in ('start_tray', 'monitor', 'connect', 'check_updates'):
                stack.enter_context(patch.object(opti_app.OptiiApp, method))
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                app.conversation = {'display_turns': [{'time': '2026-09-23 20:00',
                                                       'question': '請解釋這份文件',
                                                       'model': 'gemma4:26b · GPU',
                                                       'answer': '第一段\n第二段\n第三段'+'長'*100}]}
                render_turns(app)
                root.update_idletasks()
                def descendants(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from descendants(child)
                bodies = [widget for widget in descendants(app.visual_body) if isinstance(widget, tk.Text)]
                self.assertEqual(len(bodies), 2)
                question, answer = bodies
                self.assertEqual(question.get('1.0', 'end-1c'), '請解釋這份文件')
                self.assertEqual(answer.get('1.0', 'end-1c'), '第一段\n第二段\n第三段'+'長'*100)
                self.assertEqual(answer.cget('state'), 'disabled')
                self.assertGreaterEqual(int(answer.cget('height')), 4)
                answer.tag_add('sel', '1.0', '2.3')
                self.assertTrue(answer.bind('<Control-c>'))
                copy_selected_text(answer)
                self.assertEqual(root.clipboard_get(), '第一段\n第二段')
                answer.insert('end', '不可編輯')
                self.assertEqual(answer.get('1.0', 'end-1c'), '第一段\n第二段\n第三段'+'長'*100)
                app.conversation['display_turns'][0]['answer'] = ''
                render_turns(app)
                app.visual_answer_var.set('正在回覆：第一句\n第二句')
                root.update_idletasks()
                self.assertEqual(app.visual_answer_var.widget.get('1.0', 'end-1c'),
                                 '正在回覆：第一句\n第二句')
                self.assertEqual(app.visual_answer_var.widget.cget('state'), 'disabled')
            finally:
                app.conversation = None
                app.quit()


class SpeechHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.body = self.rfile.read(int(self.headers['Content-Length']))
        self.server.started.set()
        self.server.release.wait(6)
        try:
            self.send_response(200)
            self.send_header('X-Sample-Rate', '24000')
            self.send_header('X-Sample-Format', 's16le')
            self.end_headers()
            self.wfile.write(b'\x00\x00'*2400)
        except OSError:
            pass


class CoreTests(unittest.TestCase):
    def test_breeze_requires_one_supported_gpu_and_hides_unknown_hardware(self):
        for capacities, expected in [([], False), ([8], False), ([8, 8], False), ([12], True), ([8, 24], True)]:
            with self.subTest(capacities=capacities):
                nvml = Mock()
                nvml.nvmlDeviceGetCount.return_value = len(capacities)
                nvml.nvmlDeviceGetHandleByIndex.side_effect = lambda index: index
                nvml.nvmlDeviceGetMemoryInfo.side_effect = lambda index: SimpleNamespace(total=capacities[index]*1024**3)
                with patch.dict('sys.modules', pynvml=nvml):
                    self.assertEqual(core.breeze_hardware_available(), expected)
                nvml.nvmlShutdown.assert_called_once()
        nvml = Mock()
        nvml.nvmlInit.side_effect = RuntimeError('driver unavailable')
        with patch.dict('sys.modules', pynvml=nvml):
            self.assertFalse(core.breeze_hardware_available())

    def test_settings_roundtrip_and_invalid_devices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            config = deepcopy(core.DEFAULTS)
            config['text']['device'] = 'CPU'
            config['theme'] = 'light'
            core.save_settings(config, path)
            self.assertEqual(core.load_settings(path), config)
            config['auto_update'] = False
            self.assertTrue(core.save_settings(config, path)['auto_update'])
            self.assertTrue(core.load_settings(path)['auto_update'])
            config['speech']['provider'] = 'breeze'
            with self.assertRaisesRegex(ValueError, 'CUDA'):
                core.save_settings(config, path)
            self.assertEqual(core.load_settings(path)['speech']['provider'], 'windows')

    def test_auto_routing_keeps_vision_followups_and_explicit_text_strips_images(self):
        config = deepcopy(core.DEFAULTS)
        config['text']['model'] = 'gemma4:26b'
        messages = [{'role': 'user', 'content': '圖片', 'images': ['encoded']}, {'role': 'user', 'content': '繼續'}]
        kind, host, _, options, routed = core.route_messages(config, messages)
        self.assertEqual((kind, host, options['num_gpu']), ('vision', '127.0.0.1:11435', 0))
        config['vision']['device'] = 'GPU'
        self.assertEqual(core.route_messages(config, messages)[1], '127.0.0.1:11436')
        kind, host, model, options, routed = core.route_messages(config, messages, 'text')
        self.assertEqual((kind, host, model), ('text', '127.0.0.1:11434', 'gemma4:26b'))
        self.assertNotIn('images', routed[0])
        self.assertIn('images', messages[0])
        config['text']['device'] = 'CPU'
        self.assertEqual(core.route_messages(config, [], 'text')[3]['num_gpu'], 0)

    def test_design_and_clone_require_correct_fields(self):
        settings = deepcopy(core.DEFAULTS['speech'])
        boundary, payload = core.multipart_speech(settings, '你好')
        self.assertIn('你好'.encode(), payload)
        self.assertIn(b'name="instruction"', payload)
        self.assertNotIn(b'name="ref_audio"', payload)
        self.assertNotIn(b'fast_all', payload)
        settings['mode'] = 'clone'
        with self.assertRaises(ValueError):
            core.multipart_speech(settings, '你好')
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'聲音.wav'
            file.write_bytes(b'RIFFtest')
            settings.update(ref_audio=str(file), ref_text='參考逐字稿')
            _, payload = core.multipart_speech(settings, '你好')
            self.assertIn(b'name="ref_audio"; filename="reference.wav"', payload)
            self.assertIn('參考逐字稿'.encode(), payload)
        settings['fast_all'] = True
        self.assertIn('--fast-all', core.breeze_launch_arguments(settings))

    def test_pcm_stream_becomes_valid_wav(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), SpeechHandler)
        server.started, server.release = threading.Event(), threading.Event()
        server.release.set()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            settings = deepcopy(core.DEFAULTS['speech'])
            settings.update(provider='breeze', device='GPU', endpoint=f'http://127.0.0.1:{server.server_port}')
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)/'voice.wav'
                core.generate_breeze(settings, '測試', output)
                with wave.open(str(output)) as audio:
                    self.assertEqual((audio.getnchannels(), audio.getframerate(), audio.getnframes()), (1, 24000, 2400))
        finally:
            server.shutdown()
            server.server_close()

    def test_cancel_interrupts_speech_before_first_byte(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), SpeechHandler)
        server.started, server.release = threading.Event(), threading.Event()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = deepcopy(core.DEFAULTS['speech'])
        settings.update(provider='breeze', device='GPU', endpoint=f'http://127.0.0.1:{server.server_port}')
        errors = []
        with tempfile.TemporaryDirectory() as directory, patch.object(core, 'DATA', Path(directory)):
            job = core.SpeechJob()
            def run():
                try:
                    job.generate(settings, '測試')
                except Exception as error:
                    errors.append(str(error))
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(server.started.wait(10))
                start = time.monotonic()
                job.cancel()
                thread.join(3)
                self.assertFalse(thread.is_alive())
                self.assertLess(time.monotonic()-start, 3)
                self.assertIn('取消', errors[0])
            finally:
                server.release.set()
                server.shutdown()
                server.server_close()


class DesktopTests(unittest.TestCase):
    def test_unsupported_breeze_ui_is_absent_and_saved_provider_falls_back(self):
        saved = deepcopy(core.DEFAULTS)
        saved['speech'].update(provider='breeze', device='GPU', instruction='保留聲音設定')
        with patch.object(opti_app, 'load_settings', side_effect=lambda: deepcopy(saved)), \
             patch.object(opti_app, 'breeze_hardware_available', return_value=False), \
             patch.object(opti_app.OptiiApp, 'start_tray'), \
             patch.object(opti_app.OptiiApp, 'monitor'), \
             patch.object(opti_app, 'initialize_models', return_value=CATALOG), \
             patch.object(opti_app.SettingsWindow, 'load_voices'):
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                root.update()
                app.open_settings()
                dialog = app.settings_window
                self.assertEqual(tuple(dialog.provider_combo['values']), ('windows',))
                self.assertIsNone(dialog.breeze_box)
                self.assertNotIn('speech.mode', dialog.vars)
                self.assertNotIn('speech.fast_all', dialog.vars)
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                notebooks = [widget for widget in descendants(dialog) if isinstance(widget, opti_app.ttk.Notebook)]
                titles = [book.tab(tab, 'text') for book in notebooks for tab in book.tabs()]
                self.assertNotIn('Breeze 服務參數', titles)
                dialog.vars['speech.provider'].set('breeze')
                dialog.provider_changed()
                config = core.validate_settings(dialog.collect())
                self.assertEqual(config['speech']['provider'], 'windows')
                self.assertEqual(config['speech']['device'], 'CPU')
                self.assertEqual(config['speech']['instruction'], '保留聲音設定')
                self.assertEqual(str(dialog.voice_combo['state']), 'readonly')
                self.assertEqual(saved['speech']['provider'], 'breeze')
                self.assertTrue(app.speak_button.winfo_ismapped())
            finally:
                app.quit()

    def test_theme_settings_and_tray_preserve_conversation(self):
        with patch.object(opti_app, 'load_settings', return_value=deepcopy(core.DEFAULTS)), \
             patch.object(opti_app, 'breeze_hardware_available', return_value=True), \
             patch.object(opti_app.OptiiApp, 'start_tray'), \
             patch.object(opti_app.OptiiApp, 'monitor'), \
             patch.object(opti_app, 'initialize_models', return_value=CATALOG), \
             patch.object(opti_app, 'save_settings', side_effect=lambda value: value), \
             patch.object(opti_app.SettingsWindow, 'load_voices'):
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                root.update()
                app.write('保留對話')
                app.settings['theme'] = 'light'
                app.apply_theme()
                self.assertEqual(app.transcript.cget('bg'), opti_app.LIGHT['paper'])
                app.settings['theme'] = 'dark'
                app.apply_theme()
                self.assertIn('保留對話', app.transcript.get('1.0', 'end'))
                app.open_settings()
                dialog = app.settings_window
                dialog.set_models(CATALOG)
                self.assertEqual(tuple(dialog.model_combos['text']['values']), ('gemma4:26b', 'llama3.2-vision:latest'))
                self.assertNotIn('embed:latest', dialog.model_combos['vision']['values'])
                dialog.vars['speech.provider'].set('breeze')
                dialog.provider_changed()
                self.assertEqual(dialog.vars['speech.device'].get(), 'GPU')
                self.assertEqual(str(dialog.voice_combo.cget('state')), 'disabled')
                config = core.validate_settings(dialog.collect())
                self.assertEqual(config['speech']['provider'], 'breeze')
                dialog.destroy()
                app.tray_icon = Mock(visible=True)
                app.close()
                root.update()
                self.assertEqual(root.state(), 'withdrawn')
                app.show()
                root.update()
                self.assertEqual(root.state(), 'normal')
                root.geometry('980x740')
                root.update()
                self.assertGreater(app.input.winfo_height(), 40)
                self.assertTrue(app.send_button.winfo_ismapped())
                job = core.SpeechJob()
                job.cancel()
                app.speech_job = job
                app.extra.put(('speech_ready', (job, Path('cancelled.wav'))))
                with patch.object(opti_app.winsound, 'PlaySound') as play:
                    app.poll_extra()
                    play.assert_not_called()
                    self.assertIsNone(app.speech_job)
            finally:
                app.quit()


class ModelSetupTests(unittest.TestCase):
    def test_empty_inventory_downloads_and_checks_default(self):
        job, emit = Mock(), Mock()
        with patch.object(core, 'installed_models', side_effect=[[], CATALOG]):
            result = core.initialize_models(job, emit)
        job.pull.assert_called_once_with(emit)
        self.assertEqual(result, CATALOG)

    def test_installed_models_skip_download_and_preserve_selection(self):
        job = Mock()
        config = deepcopy(core.DEFAULTS)
        config['text']['model'] = 'gemma4:26b'
        with patch.object(core, 'installed_models', return_value=CATALOG):
            core.initialize_models(job, Mock())
        job.pull.assert_not_called()
        self.assertEqual(core.select_installed_defaults(config, CATALOG), config)
        self.assertEqual(core.DEFAULTS['text']['model'], 'llama3.2-vision:latest')

    def test_connection_failure_is_not_empty_inventory(self):
        job = Mock()
        with patch.object(core, 'installed_models', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                core.initialize_models(job, Mock())
        job.pull.assert_not_called()

    def test_download_failure_and_missing_model_propagate(self):
        job = Mock()
        job.pull.side_effect = RuntimeError('disk full')
        with patch.object(core, 'installed_models', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'disk full'):
                core.initialize_models(job, Mock())
        job.pull.side_effect = None
        with patch.object(core, 'installed_models', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, '找不到'):
                core.initialize_models(job, Mock())

    def test_routing_follows_selected_model_not_chat_slot(self):
        config = deepcopy(core.DEFAULTS)
        self.assertEqual(core.route_messages(config, [], 'text', CATALOG)[1], '127.0.0.1:11435')
        config['vision']['model'] = 'gemma4:26b'
        self.assertEqual(core.route_messages(config, [], 'vision', CATALOG)[1], '127.0.0.1:11434')
        config['text']['model'] = 'custom-alias:latest'
        catalog = [{'name': 'custom-alias:latest', 'details': {'family': 'mllama'}}]
        self.assertEqual(core.route_messages(config, [], 'text', catalog)[1], '127.0.0.1:11435')

    def test_official_pull_payload_and_progress(self):
        stream = io.BytesIO(b'{"status":"pulling","total":100,"completed":50}\n{"status":"success"}\n')
        with patch.object(opti_model_worker, 'urlopen', return_value=stream) as open_request, \
             patch('sys.stdout', new_callable=io.StringIO) as stdout:
            result = opti_model_worker.main()
            self.assertIn('"completed": 50', stdout.getvalue())
        request = open_request.call_args.args[0]
        self.assertEqual(json.loads(request.data), {'model': 'llama3.2-vision', 'stream': True})
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/pull')
        self.assertEqual(result, 0)

    def test_pull_truncation_is_not_success_and_cancel_prevents_spawn(self):
        with patch.object(opti_model_worker, 'urlopen', return_value=io.BytesIO(b'{"status":"pulling"}\n')), \
             patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaisesRegex(RuntimeError, '提前結束'):
                opti_model_worker.main()
        job = core.ModelDownload()
        job.cancel()
        with patch.object(core.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, '取消'):
                job.pull(Mock())
        launch.assert_not_called()


class CaptureTests(unittest.TestCase):
    def test_reverse_drag_scaling_clamping_and_tiny_click(self):
        self.assertEqual(opti_capture.crop_bounds((190, 90), (10, 5), (200, 100), (400, 200)), (20, 10, 380, 180))
        self.assertEqual(opti_capture.crop_bounds((-10, -20), (300, 150), (200, 100), (400, 200)), (0, 0, 400, 200))
        self.assertIsNone(opti_capture.crop_bounds((10, 10), (12, 90), (200, 100), (400, 200)))

    def test_region_crop_and_negative_monitor_origin(self):
        root = tk.Tk()
        root.update()
        callback = Mock()
        session = opti_capture.RegionCapture(root, callback)
        try:
            with patch.object(opti_capture, 'desktop_bounds', return_value=(-640, -100, 640, 200)), \
                 patch.object(opti_capture, 'position_overlay', wraps=opti_capture.position_overlay) as position, \
                 patch.object(opti_capture.ImageGrab, 'grab', return_value=Image.new('RGB', (1280, 400), 'red')):
                session.start()
                root.after_cancel(session.timer)
                self.assertEqual(root.state(), 'withdrawn')
                session.capture()
                self.assertEqual(session.view_size, (640, 200))
                position.assert_called_once_with(session.overlay, (-640, -100, 640, 200))
                session.press(SimpleNamespace(x=200, y=100))
                session.release(SimpleNamespace(x=20, y=10))
                image, error = callback.call_args.args
                self.assertIsNone(error)
                self.assertEqual(image.size, (360, 180))
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
                self.assertEqual(root.state(), 'normal')
                self.assertIsNone(session.snapshot)
        finally:
            session.cancel()
            root.destroy()

    def test_cancel_and_capture_error_restore_window(self):
        root = tk.Tk()
        root.update()
        try:
            callback = Mock()
            session = opti_capture.RegionCapture(root, callback)
            session.start()
            session.cancel()
            session.cancel()
            callback.assert_called_once_with(None, None)
            self.assertEqual(root.state(), 'normal')
            session = opti_capture.RegionCapture(root, callback)
            session.start()
            root.after_cancel(session.timer)
            with patch.object(opti_capture.ImageGrab, 'grab', side_effect=OSError('screen unavailable')):
                session.capture()
            self.assertEqual(callback.call_args.args, (None, 'screen unavailable'))
            self.assertEqual(root.state(), 'normal')
        finally:
            root.destroy()

    def test_screenshot_attaches_preserves_draft_and_cleans_only_owned_file(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(opti_app, 'load_settings', return_value=deepcopy(core.DEFAULTS)))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'start_tray'))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'monitor'))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'connect'))
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            stack.enter_context(patch.object(opti_history, 'HISTORY_DIR', directory))
            stack.enter_context(patch.object(opti_app, 'save_record', side_effect=lambda r:opti_history.save_record(r, directory)))
            stack.enter_context(patch.object(opti_app, 'list_records', side_effect=lambda:opti_history.list_records(directory)))
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                app.input.insert('1.0', '幫我看這段內容')
                app.route.set('純文字')
                app.screenshot_done(Image.new('RGB', (320, 180), 'blue'))
                path = app.pending_path
                self.assertTrue(path.is_file())
                self.assertIn('螢幕截圖', app.image_name.cget('text'))
                self.assertEqual(app.route.get(), '自動分流')
                self.assertEqual(app.input.get('1.0', 'end-1c'), '幫我看這段內容')
                app.screenshot_done(None)
                self.assertEqual(app.pending_path, path)
                self.assertTrue(path.is_file())
                with tempfile.TemporaryDirectory() as directory:
                    selected_file = Path(directory)/'user-image.png'
                    Image.new('RGB', (64, 64)).save(selected_file)
                    app.attach_image(selected_file)
                    self.assertFalse(path.exists())
                    app.clear_image()
                    self.assertTrue(selected_file.exists())
                app.screenshot_done(Image.new('RGB', (320, 180), 'blue'))
                path = app.pending_path
                app.ready = True
                app.catalog = CATALOG
                app.model_loading = False
                with patch.object(app, 'generate') as generate:
                    app.send()
                    deadline = time.monotonic()+2
                    while not generate.called and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(generate.called)
                    self.assertTrue(generate.call_args.args[1][-1]['images'])
                    self.assertFalse(path.exists())
                self.assertEqual(app.capture_files, set())
                self.assertTrue(app.conversation['display_turns'][0]['preview'])
                saved = opti_history.load_record(app.conversation['id'], directory)
                self.assertTrue(saved['display_turns'][0]['preview'])
                self.assertTrue(opti_history.preview_path(saved['id'], 0).is_file())
                app.conversation = saved
                render_turns(app)
                self.assertEqual(len(app.visual_photos), 1)
            finally:
                app.quit()




class PdfTests(unittest.TestCase):
    @staticmethod
    def text_pdf(path):
        stream = b'BT /F1 12 Tf 20 70 Td (Hello PDF document) Tj ET'
        objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
                   b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
                   b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
                   b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
        data = b'%PDF-1.4\n'
        offsets = []
        for index, obj in enumerate(objects, 1):
            offsets.append(len(data))
            data += str(index).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
        xref = len(data)
        data += b'xref\n0 6\n0000000000 65535 f \n'
        for offset in offsets:
            data += f'{offset:010d} 00000 n \n'.encode()
        data += b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF'
        path.write_bytes(data)

    def test_pdf_text_extraction_render_and_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'文件.pdf'
            self.text_pdf(path)
            document = opti_pdf.read_pdf(path)
            self.assertIn('Hello PDF document', document['text'])
            self.assertIn('第 1 頁', document['text'])
            self.assertFalse(document['truncated'])
            self.assertEqual(opti_pdf.render_page(path, 1).size, (400, 200))
            with self.assertRaises(ValueError):
                opti_pdf.render_page(path, 2)
            with patch.object(opti_pdf, 'MAX_BYTES', 1), self.assertRaises(ValueError):
                opti_pdf.read_pdf(path)
            path.write_bytes(b'not a PDF')
            with self.assertRaises(Exception):
                opti_pdf.read_pdf(path)

    def test_scanned_pdf_and_long_document_report_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'scan.pdf'
            Image.new('RGB', (100, 200), 'blue').save(path, 'PDF')
            document = opti_pdf.read_pdf(path)
            self.assertEqual(document['text'], '')
            self.assertEqual(document['empty_pages'], [1])
            self.assertGreater(opti_pdf.render_page(path, 1).height, 0)
            document['text'] = '文字內容'*10000
            content, note = opti_pdf.pdf_prompt(document, '摘要', core.DEFAULTS['text'])
            self.assertIn('部分內容', note)
            self.assertLess(len(content), 2000)
            self.text_pdf(path)
            with patch.object(opti_pdf, 'MAX_TEXT', 12):
                self.assertTrue(opti_pdf.read_pdf(path)['truncated'])

    def test_pdf_attachment_preserves_draft_sends_context_and_cleans_page(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(opti_app, 'load_settings', return_value=deepcopy(core.DEFAULTS)))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'start_tray'))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'monitor'))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'connect'))
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(patch.object(opti_app, 'save_record',
                side_effect=lambda record: opti_history.save_record(record, Path(directory)/'history')))
            stack.enter_context(patch.object(opti_app, 'list_records',
                side_effect=lambda: opti_history.list_records(Path(directory)/'history')))
            path = Path(directory)/'test.pdf'
            self.text_pdf(path)
            document = opti_pdf.read_pdf(path)
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                self.assertIn('OptiChat', root.title())
                app.input.insert('1.0', '幫我摘要')
                app.attach_pdf(document)
                self.assertEqual(app.input.get('1.0', 'end-1c'), '幫我摘要')
                self.assertEqual(app.route.get(), '純文字')
                app.ready, app.model_loading, app.catalog = True, False, CATALOG
                with patch.object(app, 'generate'):
                    app.send()
                self.assertIn('Hello PDF document', app.turn['content'])
                self.assertIn('幫我摘要', app.turn['content'])
                self.assertIsNone(app.pending_document)
                self.assertTrue(app.conversation['display_turns'][0]['attachment'].startswith('PDF：'))
                self.assertNotIn('preview', app.conversation['display_turns'][0])
                def widgets(parent):
                    for child in parent.winfo_children():
                        yield child
                        yield from widgets(child)
                pdf_icons = [widget for widget in widgets(app.visual_body) if isinstance(widget, tk.Canvas)
                             and any(widget.type(item) == 'text' and widget.itemcget(item, 'text') == 'PDF'
                                     for item in widget.find_all())]
                self.assertEqual(len(pdf_icons), 1)
                app.set_busy(False)
                app.attach_pdf(document, opti_pdf.render_page(path, 1), 1)
                image_path = app.pending_path
                self.assertEqual(app.route.get(), '自動分流')
                self.assertTrue(image_path.is_file())
                self.assertIn('第 1', app.prepare_turn('辨識')['content'])
                with patch.object(app, 'generate'):
                    app.send()
                self.assertTrue(app.conversation['display_turns'][-1]['attachment'].startswith('PDF：'))
                self.assertNotIn('preview', app.conversation['display_turns'][-1])
                self.assertFalse(image_path.exists())
                self.assertTrue(path.is_file())
            finally:
                app.quit()

    def test_drop_pdf_into_chat_and_restore_renamed_conversation(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(opti_app, 'load_settings', return_value=deepcopy(core.DEFAULTS)))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'start_tray'))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'monitor'))
            stack.enter_context(patch.object(opti_app.OptiiApp, 'connect'))
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
            store = directory/'history'
            stack.enter_context(patch.object(opti_app, 'save_record', side_effect=lambda r:opti_history.save_record(r, store)))
            stack.enter_context(patch.object(opti_app, 'list_records', side_effect=lambda:opti_history.list_records(store)))
            stack.enter_context(patch.object(opti_app, 'load_record', side_effect=lambda i:opti_history.load_record(i, store)))
            pdf = directory/'PDF 文件 with spaces.pdf'
            self.text_pdf(pdf)
            root = tk.Tk()
            app = opti_app.OptiiApp(root)
            try:
                self.assertTrue(root.tk.call('package', 'present', 'tkdnd'))
                app.input.insert('1.0', '請摘要')
                event = SimpleNamespace(data=root.tk.call('list', str(pdf)))
                app.on_drop(event)
                for _ in range(100):
                    root.update()
                    if app.pending_document:
                        break
                    time.sleep(.01)
                self.assertIsNotNone(app.pending_document)
                self.assertEqual(app.input.get('1.0', 'end-1c'), '請摘要')
                self.assertEqual(app.pending_document['path'], pdf)
                app.ready, app.model_loading, app.catalog = True, False, CATALOG
                with patch.object(app, 'generate'):
                    app.send()
                self.assertRegex(app.conversation['title'], r'^\d{4}-\d\d-\d\d \d\d:\d\d$')
                self.assertEqual(len(opti_history.list_records(store)), 1)
                app.events.put(('token', '已閱讀並整理重點。'))
                app.events.put(('complete', 'stop'))
                app.events.put(('finished', False))
                app.poll()
                self.assertEqual(app.conversation['display_turns'][0]['answer'], '已閱讀並整理重點。')
                self.assertEqual(opti_history.list_records(store)[0]['display_turns'][0]['answer'], '已閱讀並整理重點。')
                app.new_chat()
                self.assertEqual(app.conversation_list.size(), 1)
                app.conversation_list.selection_set(0)
                app.select_conversation()
                self.assertIn('請摘要', app.transcript.get('1.0', 'end-1c'))
                with patch.object(opti_app.simpledialog, 'askstring', return_value='我的報告'):
                    app.rename_conversation()
                self.assertEqual(opti_history.list_records(store)[0]['title'], '我的報告')
            finally:
                app.quit()


if __name__ == '__main__':
    unittest.main()
