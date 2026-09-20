"""OptiiChat desktop interface; all widgets are owned by the Tk thread."""
from copy import deepcopy
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import winsound
import winreg

from PIL import Image, ImageDraw, ImageTk
from llama_vision_ui import ChatApp, StreamRequest, build_messages
from opti_capture import RegionCapture
from opti_version import VERSION
from opti_update import UPDATE_DIR, check_for_update
from opti_core import (DEFAULTS, DATA, ResourceMonitor, SpeechJob, breeze_launch_arguments, breeze_hardware_available,
                       ensure_model_service, json_request, load_settings, route_messages, save_settings,
                       ModelDownload, initialize_models, model_choices, model_service_kind, select_installed_defaults)

ASSETS = Path(__file__).with_name('opti_assets')
LIGHT = dict(bg='#F3F4F1', paper='#FFFFFF', ink='#14161A', muted='#6F756F', line='#DADDD7', accent='#087E7A', gold='#89692E')
DARK = dict(bg='#14161A', paper='#202427', ink='#F3F4F1', muted='#AAB4AD', line='#394144', accent='#2FD4C8', gold='#D8B978')


def app_icon(size, background=(0, 0, 0, 0)):
    """Fit the wide brand mark inside a square Windows icon without stretching."""
    with Image.open(ASSETS/'logo-teal.png') as source:
        mark = source.convert('RGBA')
    padding = max(1, size // 16)
    mark.thumbnail((size - 2 * padding, size - 2 * padding), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (size, size), background)
    canvas.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return canvas


class OptiiApp(ChatApp):
    def __init__(self, root):
        self.config_error = None
        try:
            self.settings = load_settings()
        except Exception as error:
            self.settings = deepcopy(DEFAULTS)
            self.config_error = str(error)
        self.breeze_available = breeze_hardware_available()
        if not self.breeze_available:
            # Keep saved voice design/clone parameters, but never invoke the hidden engine.
            self.settings['speech'].update(provider='windows', device='CPU')
        self.extra = queue.Queue()
        self.shutdown = threading.Event()
        self.speech_job = None
        self.audio_path = None
        self.tray_icon = None
        self.settings_window = None
        self.roles = []
        self.active_kind = 'text'
        self.active_device = self.settings['text']['device']
        self.last_theme = None
        self.catalog = []
        self.catalog_loaded = False
        self.model_loading = True
        self.model_download = ModelDownload()
        self.capture_session = None
        self.capture_files = set()
        self.scrollbar_images = {}
        self.update_busy = False
        self.update_status = tk.StringVar(root, value='目前版本 '+VERSION)
        super().__init__(root)
        root.title('OptiiChat · 本機 AI 工作室')
        root.geometry('1180x940')
        root.minsize(980, 740)
        self.fast.set(self.settings['fast_image'])
        self.apply_theme()
        self.icon_images = [ImageTk.PhotoImage(app_icon(size)) for size in (256, 128, 64, 48, 32, 24, 20, 16)]
        root.iconphoto(True, *self.icon_images)
        self.start_tray()
        threading.Thread(target=self.monitor, daemon=True).start()
        root.after(100, self.poll_extra)
        root.after(3500, self.check_updates)
        if self.config_error:
            self.write('設定檔讀取失敗，暫用預設值；原檔尚未覆寫：'+self.config_error+'\n', 'error')

    def frame(self, parent, role='bg', **kwargs):
        widget = tk.Frame(parent, **kwargs)
        self.roles.append((widget, role, None))
        return widget

    def label(self, parent, text='', role='bg', color='ink', **kwargs):
        widget = tk.Label(parent, text=text, font=('Microsoft JhengHei UI', 10), **kwargs)
        self.roles.append((widget, role, color))
        return widget

    def _build(self):
        self.route = tk.StringVar(value='自動分流')
        self.metrics = tk.StringVar(value='CPU —   GPU —')
        self.audio_status = tk.StringVar(value='語音待命')
        style = ttk.Style(self.root)
        style.theme_use('clam')
        header = self.frame(self.root, padx=26, pady=16)
        header.pack(fill='x')
        self.logo = self.label(header)
        self.logo.pack(side='left', padx=(0, 14))
        brand = self.label(header, 'Optiimind', color='ink')
        brand.configure(font=('Georgia', 26, 'bold'))
        brand.pack(side='left')
        self.label(header, 'OPTII CHAT  /  本機 AI 工作室', color='muted').pack(side='left', padx=20)
        ttk.Button(header, text='設定', command=self.open_settings).pack(side='right')
        toolbar = self.frame(self.root, padx=26, pady=8)
        toolbar.pack(fill='x')
        self.label(toolbar, textvariable=self.status, color='accent', wraplength=530, justify='left').pack(side='left')
        self.new_button = ttk.Button(toolbar, text='新對話', command=self.new_chat)
        self.new_button.pack(side='right')
        ttk.Button(toolbar, text='複製回覆', command=self.copy_answer).pack(side='right', padx=6)
        self.capture_button = ttk.Button(toolbar, text='截圖', command=self.take_screenshot)
        self.capture_button.pack(side='right', padx=6)
        self.root.bind('<Control-Shift-S>', self.take_screenshot)
        # Reserve fixed controls before allocating the growing transcript.
        footer = self.frame(self.root, padx=26, pady=8)
        footer.pack(side='bottom', fill='x')
        self.label(footer, textvariable=self.metrics, color='muted').pack(side='left')
        self.label(footer, 'Ctrl+Enter 傳送 · × 常駐', color='muted').pack(side='right')
        composer = self.frame(self.root, padx=26, pady=10)
        composer.pack(side='bottom', fill='x')
        actions = self.frame(composer)
        actions.pack(side='right', padx=(12, 0))
        self.send_button = ttk.Button(actions, text='傳送 ↗', style='Accent.TButton', command=self.send, state='disabled')
        self.send_button.pack(fill='x')
        self.stop_button = ttk.Button(actions, text='停止初始化', command=self.stop)
        self.stop_button.pack(fill='x', pady=(6, 0))
        self.input = tk.Text(composer, height=3, wrap='word', relief='flat', padx=14, pady=10,
                             font=('Microsoft JhengHei UI', 11), undo=True)
        self.input.pack(fill='both', expand=True)
        self.roles.append((self.input, 'paper', 'ink'))
        self.input.bind('<Control-Return>', self.keyboard_send)
        body = self.frame(self.root, padx=26, pady=8)
        body.pack(fill='both', expand=True)
        sidebar = self.frame(body, width=280)
        sidebar.pack(side='right', fill='y', padx=(20, 0))
        sidebar.pack_propagate(False)
        side_scroll = ttk.Scrollbar(sidebar)
        side_scroll.pack(side='right', fill='y')
        side_canvas = tk.Canvas(sidebar, highlightthickness=0, yscrollcommand=side_scroll.set)
        self.roles.append((side_canvas, 'bg', None))
        side_canvas.pack(fill='both', expand=True)
        side_scroll.configure(command=side_canvas.yview)
        side = self.frame(side_canvas)
        side_item = side_canvas.create_window((0, 0), window=side, anchor='nw')
        side.bind('<Configure>', lambda _: side_canvas.configure(scrollregion=side_canvas.bbox('all')))
        side_canvas.bind('<Configure>', lambda event: side_canvas.itemconfigure(side_item, width=event.width))
        def side_wheel(event):
            if str(event.widget).startswith(str(sidebar)):
                side_canvas.yview_scroll(-int(event.delta/120), 'units')
        self.root.bind('<MouseWheel>', side_wheel, add=True)
        self.label(side, '模型與圖片', color='gold', anchor='w').pack(fill='x', pady=(0, 10))
        self.route_combo = ttk.Combobox(side, textvariable=self.route, values=['自動分流', '純文字', '圖片理解'], state='readonly')
        self.route_combo.pack(fill='x')
        self.model_summary = self.label(side, justify='left', anchor='w', wraplength=250, color='muted')
        self.model_summary.pack(fill='x', pady=10)
        ttk.Button(side, text='重新檢查 / 重試模型下載', command=self.refresh_models).pack(fill='x', pady=(0, 8))
        preview = self.frame(side, role='paper', height=145)
        preview.pack(fill='x')
        preview.pack_propagate(False)
        self.preview_label = self.label(preview, '尚未選擇圖片\nJPG · PNG · WEBP', role='paper', color='muted')
        self.preview_label.pack(fill='both', expand=True)
        self.image_name = self.label(side, '圖片在本機處理', color='muted', wraplength=245, anchor='w')
        self.image_name.pack(fill='x', pady=8)
        row = self.frame(side)
        row.pack(fill='x')
        self.attach_button = ttk.Button(row, text='＋ 圖片', command=self.choose_image)
        self.attach_button.pack(side='left', expand=True, fill='x')
        self.remove_button = ttk.Button(row, text='移除', command=self.clear_image, state='disabled')
        self.remove_button.pack(side='left', padx=(6, 0))
        self.fast_check = ttk.Checkbutton(side, text='快速圖片（560 px）', variable=self.fast)
        self.fast_check.pack(anchor='w', pady=(10, 16))
        self.label(side, '語音工作室' if self.breeze_available else 'Windows 本機朗讀', color='gold', anchor='w').pack(fill='x')
        self.label(side, textvariable=self.audio_status, color='muted', wraplength=245, anchor='w').pack(fill='x', pady=8)
        self.speak_button = ttk.Button(side, text='朗讀回覆 / 輸入文字', command=self.speak)
        self.speak_button.pack(fill='x')
        row = self.frame(side)
        row.pack(fill='x', pady=6)
        ttk.Button(row, text='停止語音', command=self.stop_speech).pack(side='left', expand=True, fill='x')
        ttk.Button(row, text='匯出 WAV', command=self.export_audio).pack(side='left', expand=True, fill='x', padx=(6, 0))
        chat = self.frame(body, role='paper')
        chat.pack(fill='both', expand=True)
        bar = ttk.Scrollbar(chat)
        bar.pack(side='right', fill='y')
        self.transcript = tk.Text(chat, wrap='word', state='disabled', relief='flat', padx=22, pady=20,
                                  font=('Microsoft JhengHei UI', 11), spacing3=9, yscrollcommand=bar.set)
        self.transcript.pack(fill='both', expand=True)
        bar.configure(command=self.transcript.yview)
        self.roles.append((self.transcript, 'paper', 'ink'))
        self.write('從一句話，或一張圖片開始。\n', 'assistant')
        self.write('在設定中選擇本機模型，附上圖片會自動切換至圖片模型。\n右側可朗讀回覆，也可以先輸入文字再產生語音。\n\n', 'note')
        self.input.focus_set()

    def resolved_theme(self):
        if self.settings['theme'] != 'system':
            return self.settings['theme']
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
                return 'light' if winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] else 'dark'
        except OSError:
            return 'light'

    def apply_theme(self):
        theme = self.resolved_theme()
        self.last_theme = theme
        p = DARK if theme == 'dark' else LIGHT
        self.root.configure(bg=p['bg'])
        remaining = []
        for widget, bg, fg in self.roles:
            if widget.winfo_exists():
                widget.configure(bg=p[bg])
                if fg:
                    widget.configure(fg=p[fg])
                if isinstance(widget, tk.Text):
                    widget.configure(insertbackground=p['ink'], selectbackground=p['accent'])
                remaining.append((widget, bg, fg))
        self.roles = remaining
        style = ttk.Style(self.root)
        style.configure('.', font=('Microsoft JhengHei UI', 10), background=p['bg'], foreground=p['ink'])
        style.configure('TButton', padding=(10, 7), background=p['paper'], foreground=p['ink'], borderwidth=0)
        style.map('TButton', background=[('active', p['line'])], foreground=[('disabled', p['muted'])])
        style.configure('Accent.TButton', background='#0ABAB5', foreground='#101817')
        style.map('Accent.TButton', background=[('active', '#2FD4C8'), ('disabled', p['line'])])
        style.configure('TEntry', fieldbackground=p['paper'], foreground=p['ink'], insertcolor=p['ink'])
        style.configure('TCombobox', fieldbackground=p['paper'], foreground=p['ink'], arrowcolor=p['ink'])
        style.map('TCombobox', fieldbackground=[('readonly', p['paper'])], foreground=[('readonly', p['ink'])])
        style.configure('TNotebook.Tab', padding=(14, 8))
        style.map('TNotebook.Tab', background=[('selected', p['paper'])])
        self.style_scrollbars(style, theme, p)
        self.root.option_add('*TCombobox*Listbox.background', p['paper'])
        self.root.option_add('*TCombobox*Listbox.foreground', p['ink'])
        for tag, color in [('user', 'accent'), ('assistant', 'gold'), ('note', 'muted')]:
            self.transcript.tag_configure(tag, foreground=p[color], font=('Microsoft JhengHei UI', 10, 'bold' if tag != 'note' else 'normal'))
        self.transcript.tag_configure('error', foreground='#E57373' if theme == 'dark' else '#A23F3F')
        logo = Image.open(ASSETS/('logo-white.png' if theme == 'dark' else 'logo-black.png')).convert('RGBA')
        logo.thumbnail((74, 44), Image.Resampling.LANCZOS)
        self.logo_photo = ImageTk.PhotoImage(logo)
        self.logo.configure(image=self.logo_photo)
        self.model_summary.configure(text=f"文字 · {self.settings['text']['model']} / {self.settings['text']['device']}\n圖片 · {self.settings['vision']['model']} / {self.settings['vision']['device']}")

    def style_scrollbars(self, style, theme, palette):
        # Keep ttk's native dragging, page scrolling, and keyboard behavior.
        # A nine-slice image gives the thumb round caps at any track length.
        scale = max(1.0, float(self.root.tk.call('tk', 'scaling')) / (96 / 72))
        width = round(16 * scale)
        height = round(28 * scale)
        inset = round(4 * scale)
        radius = (width - 2 * inset) // 2
        element = f'Optii.{theme}.Vertical.Scrollbar.thumb'
        if theme not in self.scrollbar_images:
            colors = ('#59666B', '#1DABA6', '#2FD4C8') if theme == 'dark' else ('#B8C4C0', '#48BDB5', '#087E7A')
            images = []
            for color in colors:
                thumb = Image.new('RGBA', (width * 4, height * 4))
                draw = ImageDraw.Draw(thumb)
                draw.rounded_rectangle((inset * 4, 2 * 4, (width-inset) * 4 - 1, (height-2) * 4 - 1),
                                       radius=radius * 4, fill=color)
                images.append(ImageTk.PhotoImage(thumb.resize((width, height), Image.Resampling.LANCZOS)))
            self.scrollbar_images[theme] = images
            style.element_create(element, 'image', images[0], ('pressed', images[2]), ('active', images[1]),
                                 border=(0, radius + 2, 0, radius + 2), sticky='nswe')
        style.layout('Vertical.TScrollbar', [('Vertical.Scrollbar.trough', {
            'sticky': 'nswe', 'children': [(element, {'sticky': 'nswe', 'expand': '1'})]})])
        style.configure('Vertical.TScrollbar', width=width, arrowsize=0, borderwidth=0,
                        relief='flat', troughcolor=palette['bg'], bordercolor=palette['bg'],
                        lightcolor=palette['bg'], darkcolor=palette['bg'])

    def connect(self):
        try:
            catalog = initialize_models(self.model_download, lambda event: self.events.put(('model_progress', event)))
            if self.model_download.cancelled.is_set():
                raise RuntimeError('模型初始化已取消。')
            self.events.put(('models_ready', catalog))
        except Exception as error:
            self.events.put(('models_error', str(error)))

    def take_screenshot(self, event=None):
        if self.busy or self.capture_session or self.closed:
            return 'break'
        self.capture_button.configure(state='disabled')
        self.status.set('拖曳框選截圖範圍；Esc 或右鍵取消。')
        self.capture_session = RegionCapture(self.root, self.screenshot_done, (self.settings_window,))
        self.capture_session.start()
        return 'break'

    def screenshot_done(self, image, error=None):
        self.capture_session = None
        if self.shutdown.is_set() or self.closed:
            return
        self.capture_button.configure(state='disabled' if self.busy else 'normal')
        self.root.lift()
        self.input.focus_force()
        if error:
            self.status.set('截圖失敗；原圖片與輸入內容已保留。')
            messagebox.showerror('無法截圖', error, parent=self.root)
            return
        if image is None:
            self.status.set('已取消截圖')
            return
        path = None
        try:
            with tempfile.NamedTemporaryFile(prefix='OptiiChat-shot-', suffix='.png', delete=False) as temporary:
                path = Path(temporary.name)
            self.capture_files.add(path)
            image.save(path, format='PNG')
            self.attach_image(path)
            if self.pending_path != path:
                self.remove_capture_file(path)
                return
            if self.route.get() == '純文字':
                self.route.set('自動分流')
            self.image_name.configure(text=f'螢幕截圖 · {image.width} × {image.height}')
            self.status.set('截圖已附加 · 輸入問題後按傳送')
        except Exception as error:
            self.remove_capture_file(path)
            self.status.set('截圖附加失敗')
            messagebox.showerror('無法附加截圖', str(error), parent=self.root)

    def remove_capture_file(self, path):
        if path in self.capture_files:
            try:
                path.unlink(missing_ok=True)
                self.capture_files.discard(path)
            except OSError:
                pass  # Retry our own temporary file at exit if it is briefly locked.

    def attach_image(self, filename):
        previous = self.pending_path
        super().attach_image(filename)
        if self.pending_path != previous:
            self.remove_capture_file(previous)

    def clear_image(self):
        previous = self.pending_path
        super().clear_image()
        self.remove_capture_file(previous)

    def set_busy(self, busy):
        super().set_busy(busy)
        self.capture_button.configure(state='disabled' if busy or self.capture_session else 'normal')

    def refresh_models(self):
        if self.model_loading or self.busy or self.speech_job:
            return
        self.model_loading = True
        self.ready = False
        self.model_download = ModelDownload()
        self.send_button.configure(state='disabled')
        self.stop_button.configure(text='停止初始化', state='normal')
        self.status.set('正在檢查本機模型…')
        threading.Thread(target=self.connect, daemon=True).start()

    def stop(self):
        if self.model_loading:
            self.model_download.cancel()
            self.status.set('正在停止模型初始化…')
            return
        super().stop()

    def route_mode(self):
        return {'自動分流': 'auto', '純文字': 'text', '圖片理解': 'vision'}[self.route.get()]

    def assistant_name(self, turn):
        kind, *_ = route_messages(self.settings, build_messages(self.history, turn), self.route_mode())
        return self.settings[kind]['model'] + ' · ' + self.settings[kind]['device']

    def create_request(self, messages):
        kind, host, model, options, routed = route_messages(self.settings, messages, self.route_mode(), self.catalog)
        self.active_kind = kind
        self.active_device = self.settings[kind]['device']
        messages[:] = routed
        info = next((item for item in self.catalog if item['name'] == model), {})
        request = StreamRequest(host, model, options, think=False if 'thinking' in info.get('capabilities', []) else None)
        request.kind, request.device = model_service_kind(model, self.catalog), self.active_device
        return request

    def generate(self, request, messages):
        try:
            ensure_model_service(request.kind, request.device)
            request.stream(messages, lambda kind, value: self.events.put((kind, value)))
        except Exception as error:
            if not request.cancelled.is_set():
                self.events.put(('error', str(error)))
        finally:
            self.events.put(('finished', request.cancelled.is_set()))

    def send(self):
        if not self.ready or self.model_loading:
            return
        if self.speech_job:
            self.status.set('請先停止或等待語音生成完成。')
            return
        if self.route_mode() == 'text' and self.pending_path:
            self.status.set('目前是純文字模式；請切換自動分流或圖片理解。')
            return
        pending = {'role': 'user', 'content': ''}
        if self.pending_path:
            pending['images'] = ['pending']
        kind, *_ = route_messages(self.settings, build_messages(self.history, pending), self.route_mode(), self.catalog)
        if self.settings[kind]['model'] not in model_choices(self.catalog, kind):
            self.status.set('目前選取的模型未安裝或不支援此功能，請在設定重新選擇。')
            return
        super().send()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'model_progress':
                    total = value.get('total', 0)
                    completed = value.get('completed', 0)
                    self.status.set(f'下載 llama3.2-vision · {completed / total:.0%} · {completed/1024**3:.2f}/{total/1024**3:.2f} GiB' if total else value.get('status', '正在下載…'))
                elif kind == 'models_ready':
                    self.catalog = value
                    updated = select_installed_defaults(self.settings, value)
                    try:
                        if not self.config_error and (updated != self.settings or not (DATA/'settings.json').exists()):
                            save_settings(updated)
                    except Exception as error:
                        self.write('預設模型設定無法保存：'+str(error)+'\n', 'error')
                    self.settings = updated
                    self.catalog_loaded = True
                    self.model_loading = False
                    self.ready = True
                    self.status.set(f'● 已就緒 · 已安裝 {len(value)} 個模型')
                    self.stop_button.configure(text='停止回覆')
                    self.set_busy(False)
                    self.apply_theme()
                    if self.settings_window and self.settings_window.winfo_exists():
                        self.settings_window.set_models(value)
                elif kind == 'models_error':
                    self.model_loading = False
                    self.status.set('模型初始化未完成 · 可按「重新檢查 / 重試模型下載」')
                    self.stop_button.configure(text='停止回覆', state='disabled')
                    self.write('\n模型：'+value+'\n', 'error')
                elif kind == 'token':
                    self.answer += value
                    self.write(value)
                elif kind == 'complete':
                    self.history.extend([self.turn, {'role': 'assistant', 'content': self.answer}])
                    self.history = self.history[-6:]
                    self.last_answer = self.answer
                    self.completed_turn = True
                    if value == 'length':
                        self.write('\n（已達長度上限，可輸入「請繼續」。）', 'note')
                elif kind == 'error':
                    self.write('\n回覆失敗：'+value+'\n', 'error')
                    self.completed_turn = False
                elif kind == 'finished':
                    if value:
                        self.write('\n（已停止，未加入後續對話。）', 'note')
                    self.write('\n\n')
                    self.status.set(f'● {self.active_kind} / {self.active_device} · {int(time.monotonic()-self.started)} 秒')
                    self.set_busy(False)
                    self.request = None
                    if self.settings['auto_speak'] and getattr(self, 'completed_turn', False) and not value:
                        self.speak(self.last_answer)
                    self.completed_turn = False
        except queue.Empty:
            pass
        self.root.after(70, self.poll)

    def tick(self):
        if self.closed:
            return
        if self.busy:
            self.status.set(f"{'正在回覆' if self.answer else '正在載入／思考'} · {int(time.monotonic()-self.started)} 秒 · {self.active_device}")
        if self.resolved_theme() != self.last_theme:
            self.apply_theme()
        self.root.after(1000, self.tick)

    def monitor(self):
        monitor = None
        try:
            monitor = ResourceMonitor()
            while not self.shutdown.wait(2):
                self.extra.put(('metrics', monitor.sample()))
        except Exception:
            self.extra.put(('metrics_error', None))
        finally:
            if monitor:
                monitor.close()

    def start_tray(self):
        try:
            import pystray
            icon = app_icon(256, '#14161A')
            def action(name):
                return lambda *_: self.extra.put((name, None))
            self.tray_icon = pystray.Icon('OptiiChat', icon, 'OptiiChat · 本機 AI 工作室', pystray.Menu(
                pystray.MenuItem('開啟 OptiiChat', action('show'), default=True),
                pystray.MenuItem('設定', action('settings')),
                pystray.MenuItem('結束程式', action('quit'))))
            def run():
                try:
                    self.tray_icon.run()
                except Exception as error:
                    self.extra.put(('tray_error', str(error)))
            threading.Thread(target=run, daemon=True).start()
        except Exception as error:
            self.extra.put(('tray_error', str(error)))

    def poll_extra(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.extra.get_nowait()
                if kind == 'metrics':
                    gpu = 'N/A' if value['gpu'] is None else f"{value['gpu']}%"
                    vram = '' if value['vram'] is None else f" · VRAM {value['vram'][0]:.1f}/{value['vram'][1]:.0f} GB"
                    self.metrics.set(f"CPU {value['cpu']:.0f}% · RAM {value['ram']:.0f}%   GPU {gpu}"+vram)
                elif kind == 'metrics_error':
                    self.metrics.set('CPU / GPU 監控無法使用')
                elif kind == 'show':
                    self.show()
                elif kind == 'settings':
                    self.show()
                    self.open_settings()
                elif kind == 'quit':
                    self.quit()
                    return
                elif kind == 'tray_error':
                    self.status.set('系統匣不可用；關閉視窗將改為最小化。')
                elif kind == 'speech_ready':
                    job, path = value
                    if self.speech_job is not job:
                        continue
                    self.speech_job = None
                    if job.cancelled.is_set():
                        self.audio_status.set('語音已取消')
                        continue
                    self.audio_path = path
                    self.audio_status.set('語音已產生 · 播放中')
                    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
                elif kind == 'speech_error':
                    job, detail = value
                    if self.speech_job is not job:
                        continue
                    self.speech_job = None
                    self.audio_status.set('語音未完成')
                    self.write('\n語音：'+detail+'\n', 'error')
                elif kind == 'health':
                    messagebox.showinfo('Breeze 連線測試', value, parent=self.settings_window or self.root)
                elif kind == 'voices':
                    if self.settings_window and self.settings_window.winfo_exists():
                        self.settings_window.set_voices(value)
                elif kind == 'update':
                    self.update_busy = False
                    self.update_status.set(value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_extra)

    def check_updates(self, force=False):
        if self.closed or self.update_busy or (not force and not self.settings['auto_update']):
            return
        error_file = UPDATE_DIR/'last-error.txt'
        if not force and error_file.exists():
            self.update_status.set('上次更新未套用：'+error_file.read_text(encoding='utf-8'))
            return
        self.update_busy = True
        self.update_status.set('正在檢查更新…')
        def run():
            try:
                result = check_for_update(force=force)
            except Exception as error:
                result = '更新檢查未完成：'+str(error)
            self.extra.put(('update', result))
        threading.Thread(target=run, daemon=True).start()

    def speak(self, text=None):
        if self.busy or self.speech_job:
            self.audio_status.set('請先等待目前工作，或按停止。')
            return
        text = text or self.input.get('1.0', 'end-1c').strip() or self.last_answer
        if not text:
            self.audio_status.set('先輸入文字，或取得模型回覆。')
            return
        self.stop_speech()
        job = self.speech_job = SpeechJob()
        settings = deepcopy(self.settings['speech'])
        self.audio_status.set('正在產生語音…')
        def run():
            try:
                path = job.generate(settings, text)
                if job.cancelled.is_set():
                    raise RuntimeError('語音已取消。')
                self.extra.put(('speech_ready', (job, path)))
            except Exception as error:
                self.extra.put(('speech_error', (job, str(error))))
        threading.Thread(target=run, daemon=True).start()

    def stop_speech(self):
        if self.speech_job:
            self.speech_job.cancel()
        winsound.PlaySound(None, 0)
        self.audio_status.set('語音已停止')

    def export_audio(self):
        if not self.audio_path:
            self.audio_status.set('請先產生一段語音。')
            return
        path = filedialog.asksaveasfilename(title='匯出語音', defaultextension='.wav', filetypes=[('WAV 音訊', '*.wav')])
        if path:
            shutil.copyfile(self.audio_path, path)
            self.audio_status.set('已匯出 WAV')

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        self.settings_window = SettingsWindow(self)
        self.apply_theme()

    def show(self):
        if self.capture_session:
            self.capture_session.cancel()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def close(self):
        if self.settings['tray']:
            if self.tray_icon and self.tray_icon.visible:
                if self.settings_window and self.settings_window.winfo_exists():
                    self.settings_window.destroy()
                self.root.withdraw()
            else:
                self.root.iconify()
        else:
            self.quit()

    def quit(self):
        self.shutdown.set()
        if self.capture_session:
            self.capture_session.cancel()
        for path in tuple(self.capture_files):
            self.remove_capture_file(path)
        self.model_download.cancel()
        self.stop_speech()
        if self.tray_icon:
            self.tray_icon.stop()
        super().close()


class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('OptiiChat 設定')
        self.geometry('860x790')
        self.minsize(780, 710)
        self.transient(app.root)
        self.vars = {}
        self.native_voices = []
        controls = ttk.Frame(self, padding=12)
        controls.pack(side='bottom', fill='x')
        ttk.Button(controls, text='儲存設定', style='Accent.TButton', command=self.save).pack(side='right')
        ttk.Button(controls, text='取消', command=self.destroy).pack(side='right', padx=8)
        self.notice = tk.StringVar(value='設定儲存後，下次生成時生效。')
        ttk.Label(controls, textvariable=self.notice).pack(side='left')
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=14, pady=14)
        general = self.tab(notebook, '外觀與常駐')
        self.field(general, '主題', 'theme', ['system', 'light', 'dark'])
        self.note(general, 'system 跟隨 Windows；light 亮色；dark 暗色。')
        self.check(general, '關閉視窗時收至右下角系統匣', 'tray')
        self.check(general, '模型完成回覆後自動朗讀', 'auto_speak')
        self.check(general, '預設快速圖片模式（560 px）', 'fast_image')
        self.check(general, '啟動時自動檢查及下載更新', 'auto_update')
        self.note(general, '新版下載後於下次啟動自動套用，不會中斷對話。\n更新只更換程式檔案，保留設定與模型。')
        ttk.Label(general, textvariable=app.update_status, wraplength=680).pack(anchor='w', pady=8)
        ttk.Button(general, text='立即檢查更新', command=lambda: app.check_updates(True)).pack(anchor='w')
        self.note(general, '系統匣右鍵可開啟設定或結束程式。\n聊天紀錄只存於記憶體，結束程式即清除。\nCPU／GPU 數值是整台電腦的即時使用率。\n\n介面與原始標誌取自 optiimind.com，為你的本機工具。')
        models = self.tab(notebook, '聊天模型')
        self.model_combos = {}
        self.model_notice = tk.StringVar(value='讀取已安裝模型中…')
        ttk.Button(models, text='重新整理已安裝模型', command=self.app.refresh_models).pack(anchor='e')
        ttk.Label(models, textvariable=self.model_notice, wraplength=700).pack(anchor='w', pady=6)
        for key, title in [('text', '文字聊天模型'), ('vision', '圖片理解模型')]:
            box = ttk.LabelFrame(models, text=title, padding=12)
            box.pack(fill='x', pady=8)
            self.model_combos[key] = self.field(box, '已安裝模型', key+'.model', [])
            self.field(box, '運算裝置', key+'.device', ['CPU', 'GPU'])
            self.field(box, 'GPU 層數（-1 自動）', key+'.gpu_layers')
            self.field(box, 'Context / 上下文長度', key+'.context')
            self.field(box, '最多輸出 tokens', key+'.max_tokens')
            self.field(box, 'Temperature（0～2）', key+'.temperature')
        self.note(models, '文字選單列出聊天模型；圖片選單只列出支援看圖的模型。\n首次啟動若完全沒有模型，會自動從 Ollama 官方下載 llama3.2-vision。\nCPU 強制 num_gpu=0；GPU 依層數卸載，部分運算仍可能使用 RAM。\nLlama 3.2 Vision 使用相容服務；其他模型使用一般 Ollama。')
        speech = self.tab(notebook, '語音')
        self.provider_combo = provider = self.field(speech, '語音引擎', 'speech.provider',
                                                   ['windows', 'breeze'] if app.breeze_available else ['windows'])
        provider.bind('<<ComboboxSelected>>', lambda _: self.provider_changed())
        self.device_widget = self.field(speech, '語音運算裝置', 'speech.device', ['CPU', 'GPU'])
        self.device_widget.configure(state='disabled')
        self.note(speech, 'Windows 使用 CPU，可直接朗讀，不需另外下載語音模型。')
        self.native_box = ttk.LabelFrame(speech, text='Windows 本機語音', padding=10)
        self.native_box.pack(fill='x', pady=8)
        self.voice_combo = self.field(self.native_box, '已安裝聲音', 'speech.voice_id', [''])
        self.field(self.native_box, '語速（80～350）', 'speech.rate')
        self.field(self.native_box, '音量（0～1）', 'speech.volume')
        self.breeze_box = None
        if app.breeze_available:
            self.breeze_box = ttk.LabelFrame(speech, text='Breeze-TTS-2', padding=10)
            self.breeze_box.pack(fill='x', pady=8)
            self.field(self.breeze_box, '服務網址', 'speech.endpoint')
            ttk.Button(self.breeze_box, text='測試服務 / health', command=self.health).pack(anchor='e')
            self.field(self.breeze_box, 'Voice Design / Clone', 'speech.mode', ['design', 'clone'])
            self.field(self.breeze_box, '聲音描述 / Direction', 'speech.instruction')
            self.field(self.breeze_box, 'Clone 參考音檔', 'speech.ref_audio')
            ttk.Button(self.breeze_box, text='選擇參考音檔', command=self.choose_reference).pack(anchor='e')
            self.field(self.breeze_box, '音檔正確逐字稿', 'speech.ref_text')
            self.field(self.breeze_box, 'CFG Scale（>0）', 'speech.cfg_scale')
            self.field(self.breeze_box, 'Seed', 'speech.seed')
            self.note(speech, 'design：以描述設計聲音；clone：需音檔及逐字稿，可加 Direction。\nBreeze 會將文字與參考音檔傳至所填服務；Windows 不使用這些參數。')
            advanced = self.tab(notebook, 'Breeze 服務參數')
            self.note(advanced, '以下是官方服務啟動參數，需要在服務端重啟才生效。\n儲存設定只保存選項，不會遠端更改已執行的服務。')
            for key in ['fast_all', 'fast_text_encoder', 'fast_backbone_prefill', 'fast_backbone_decode', 'fast_depth_decoder', 'fast_codec']:
                self.check(advanced, '--'+key.replace('_', '-'), 'speech.'+key)
            ttk.Button(advanced, text='複製服務啟動命令', command=self.copy_command).pack(anchor='w', pady=14)
            self.note(advanced, '將命令中的 PATH_TO_BREEZE_TTS_2 替換成模型目錄。\n預設 eager 約需 7.7 GiB，建議 12 GB GPU；fast-all 建議 24 GB。\n\n官方 API 固定值：max_new_tokens=1500、max_seq_len=2048、\nrepetition_penalty=1.1。這些不是可傳入的請求參數。\n輸出格式：24 kHz / mono / 16-bit PCM（本程式封裝為 WAV）。\n\n權重與產出限研究及非商業使用，詳見模型授權。\n完整安裝方式見 OptiiChat-使用說明.md。')
        self.provider_changed()
        self.set_models(app.catalog if app.catalog_loaded else None)
        threading.Thread(target=self.load_voices, daemon=True).start()

    def tab(self, notebook, title):
        outer = ttk.Frame(notebook)
        notebook.add(outer, text=title)
        canvas = tk.Canvas(outer, highlightthickness=0)
        self.app.roles.append((canvas, 'bg', None))
        bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        bar.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        canvas.configure(yscrollcommand=bar.set)
        body = ttk.Frame(canvas, padding=16)
        item = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        def wheel(event):
            if str(event.widget).startswith(str(outer)):
                canvas.yview_scroll(-int(event.delta/120), 'units')
        self.bind('<MouseWheel>', wheel, add=True)
        return body

    def variable(self, key, boolean=False):
        value = self.app.settings
        for part in key.split('.'):
            value = value[part]
        var = (tk.BooleanVar if boolean else tk.StringVar)(self, value=value)
        self.vars[key] = var
        return var

    def field(self, parent, title, key, choices=None):
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=title, width=24).pack(side='left')
        var = self.variable(key)
        widget = ttk.Entry(row, textvariable=var) if choices is None else ttk.Combobox(row, textvariable=var, values=choices, state='readonly')
        widget.pack(side='left', fill='x', expand=True)
        return widget

    def note(self, parent, text):
        ttk.Label(parent, text=text, wraplength=700, justify='left').pack(anchor='w', pady=10)

    def check(self, parent, title, key):
        ttk.Checkbutton(parent, text=title, variable=self.variable(key, True)).pack(anchor='w', pady=7)

    def provider_changed(self):
        if not self.app.breeze_available:
            self.vars['speech.provider'].set('windows')
        breeze = self.vars['speech.provider'].get() == 'breeze'
        self.vars['speech.device'].set('GPU' if breeze else 'CPU')
        def state_tree(parent, enabled):
            for child in parent.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Combobox, ttk.Button)):
                    child.configure(state=('readonly' if isinstance(child, ttk.Combobox) else 'normal') if enabled else 'disabled')
                state_tree(child, enabled)
        state_tree(self.native_box, not breeze)
        if self.breeze_box is not None:
            state_tree(self.breeze_box, breeze)

    def collect(self):
        settings = deepcopy(self.app.settings)
        for key, var in self.vars.items():
            if '.' in key:
                group, name = key.split('.')
                settings[group][name] = var.get()
            else:
                settings[key] = var.get()
        name = settings['speech']['voice_id']
        settings['speech']['voice_id'] = next((voice['id'] for voice in self.native_voices if voice['name'] == name), name)
        return settings

    def save(self):
        try:
            if self.app.model_loading:
                raise ValueError('請先等待模型清單讀取或下載完成。')
            for kind in ('text', 'vision'):
                selected = self.vars[kind+'.model'].get()
                if selected != self.app.settings[kind]['model'] and selected not in model_choices(self.app.catalog, kind):
                    raise ValueError('請從已安裝模型的下拉選單選擇。')
            self.app.settings = save_settings(self.collect())
            self.app.fast.set(self.app.settings['fast_image'])
            self.app.apply_theme()
            self.app.status.set('設定已儲存')
            self.destroy()
        except Exception as error:
            messagebox.showerror('設定未儲存', str(error), parent=self)

    def choose_reference(self):
        path = filedialog.askopenfilename(parent=self, filetypes=[('音訊', '*.wav *.mp3 *.flac *.m4a *.ogg'), ('所有檔案', '*.*')])
        if path:
            self.vars['speech.ref_audio'].set(path)

    def health(self):
        endpoint = self.vars['speech.endpoint'].get().rstrip('/')
        def run():
            try:
                data = json_request(endpoint+'/health', timeout=8)
                message = '服務已連線：'+json.dumps(data, ensure_ascii=False)
            except Exception as error:
                message = '尚未連線：'+str(error)
            self.app.extra.put(('health', message))
        threading.Thread(target=run, daemon=True).start()

    def copy_command(self):
        command = ' '.join(breeze_launch_arguments(self.collect()['speech']))
        self.clipboard_clear()
        self.clipboard_append(command)
        self.notice.set('已複製；請於 CUDA 服務環境執行。')

    def load_voices(self):
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('opti_speech_worker.py')), '--voices'],
                                    capture_output=True, timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.app.extra.put(('voices', json.loads(result.stdout)))
        except Exception:
            pass

    def set_voices(self, voices):
        self.native_voices = voices
        self.voice_combo.configure(values=['']+[voice['name'] for voice in voices])
        current = self.vars['speech.voice_id'].get()
        self.vars['speech.voice_id'].set(next((voice['name'] for voice in voices if voice['id'] == current), current))

    def set_models(self, catalog):
        if catalog is None:
            self.model_notice.set('模型清單尚未就緒；可按重新整理。')
            return
        missing = []
        for kind, combo in self.model_combos.items():
            choices = model_choices(catalog, kind)
            combo.configure(values=choices, state='readonly' if choices else 'disabled')
            if self.vars[kind+'.model'].get() not in choices:
                preferred = self.app.settings[kind]['model']
                if preferred in choices:
                    self.vars[kind+'.model'].set(preferred)
                elif choices:
                    self.vars[kind+'.model'].set(choices[0])
                else:
                    missing.append('圖片' if kind == 'vision' else '文字')
        self.model_notice.set('已讀取本機模型。' if not missing else '尚無可用的'+ '、'.join(missing)+'模型。')


if __name__ == '__main__':
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    instance = kernel.CreateMutexW(None, False, 'Local\\OptiiChat.Desktop.Instance')
    already_running = ctypes.get_last_error() == 183
    show_event = kernel.CreateEventW(None, False, False, 'Local\\OptiiChat.Desktop.Show')
    if already_running:
        kernel.SetEvent(show_event)
        sys.exit(0)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('OptiiChat.Desktop')
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    app = OptiiApp(root)
    def watch_open():
        while not app.shutdown.is_set():
            if kernel.WaitForSingleObject(show_event, 1000) == 0:
                app.extra.put(('show', None))
    threading.Thread(target=watch_open, daemon=True).start()
    root.mainloop()
