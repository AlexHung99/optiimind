"""OptiiChat desktop interface; all widgets are owned by the Tk thread."""
from copy import deepcopy
import ctypes
from datetime import datetime
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
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter import font as tkfont
import webbrowser
import winsound
import winreg

from PIL import Image, ImageDraw, ImageTk
from llama_vision_ui import ChatApp, StreamRequest, build_messages, prepare_image
from opti_capture import RegionCapture
from opti_pdf import PdfPicker, pdf_prompt, prepare_pdf, inspect_pdf
from opti_history import (new_record, save_record, list_records, load_record, save_preview,
                          save_attachment, delete_record)
from opti_version import VERSION
from opti_update import UPDATE_DIR, check_for_update
from opti_core import (DEFAULTS, DATA, ResourceMonitor, SpeechJob, breeze_launch_arguments, breeze_hardware_available,
                       ensure_model_service, json_request, load_settings, route_messages, save_settings,
                       ModelDownload, initialize_models, installed_models, model_choices, model_service_kind,
                       select_installed_defaults, validate_model_name)

ASSETS = Path(__file__).with_name('opti_assets')
LIGHT = dict(bg='#EAF3F5', rail='#DFEBEF', panel='#F7FBFD', chat='#FFFFFF',
             user_card='#E3F8FA', assistant_card='#F3F8FA', input='#FFFFFF', selected='#C6F1F3',
             paper='#FFFFFF', ink='#142A38', muted='#647D8E', line='#B8D1D9', accent='#087E88', gold='#986200')
DARK = dict(bg='#091720', rail='#0A1925', panel='#102330', chat='#0D1C27',
            user_card='#103344', assistant_card='#172D3A', input='#142B39', selected='#0A3D4B',
            paper='#132735', ink='#EDF4FA', muted='#9DAFBE', line='#29495B', accent='#38E3EE', gold='#F3CA68')


def ui_font_family(root):
    """Use an installed Traditional Chinese UI font for text throughout the app."""
    try:
        available = {name.casefold(): name for name in tkfont.families(root)}
    except tk.TclError:
        available = {}
    for preferred in ('Microsoft JhengHei UI', 'Microsoft JhengHei', 'Noto Sans CJK TC',
                      'Noto Sans TC', 'Arial Unicode MS', 'Segoe UI'):
        if preferred.casefold() in available:
            return available[preferred.casefold()]
    try:
        return tkfont.nametofont('TkDefaultFont', root=root).actual('family')
    except tk.TclError:
        return 'Segoe UI'


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
        self.ui_font = ui_font_family(root)
        self.config_error = None
        try:
            self.settings = load_settings()
        except Exception as error:
            self.settings = deepcopy(DEFAULTS)
            self.config_error = str(error)
        self.first_setup = not (DATA/'settings.json').exists()
        self.breeze_available = breeze_hardware_available()
        if not self.breeze_available:
            # Keep saved voice design/clone parameters, but never invoke the hidden engine.
            self.settings['speech'].update(provider='windows', device='CPU')
        self.extra = queue.Queue()
        self.shutdown = threading.Event()
        self.speech_job = None
        self.audio_path = None
        self.tray_icon = None
        self.tray_hint_shown = False
        self.tray_unavailable_warned = False
        self.settings_window = None
        self.about_window = None
        self.roles = []
        self.active_kind = 'text'
        self.active_device = self.settings['text']['device']
        self.last_theme = None
        self.catalog = []
        self.catalog_loaded = False
        self.model_loading = True
        self.model_download = ModelDownload()
        self.catalog_download_job = None
        self.catalog_download_status = '輸入模型名稱後按「下載模型」。'
        self.catalog_download_percent = 0
        self.capture_session = None
        self.capture_files = set()
        self.pending_thumbnail = None
        self.visual_photos = []
        self.pending_document = None
        self.pdf_image_note = ''
        self.pdf_source = None
        self.pdf_job = None
        self.conversation = None
        self.conversation_index = []
        self.scrollbar_images = {}
        self.update_busy = False
        self.update_on_exit_started = False
        self.update_status = tk.StringVar(root, value='目前版本 '+VERSION)
        super().__init__(root)
        root.title('OptiChat · 本機 AI')
        root.geometry('1410x960')
        root.minsize(1050, 740)
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
        widget = tk.Label(parent, text=text, font=(self.ui_font, 10), **kwargs)
        self.roles.append((widget, role, color))
        return widget

    def _build(self):
        from opti_ui import build_ui
        build_ui(self)

    def refresh_conversations(self):
        self.conversation_index = list_records()
        self._listing = True
        try:
            self.conversation_list.delete(0, 'end')
            for record in self.conversation_index:
                self.conversation_list.insert('end', record.get('title', '未命名對話'))
            if self.conversation:
                for index, record in enumerate(self.conversation_index):
                    if record['id'] == self.conversation['id']:
                        self.conversation_list.selection_set(index)
                        break
        finally:
            self._listing = False
        from opti_ui import build_history_cards
        build_history_cards(self)

    def persist_conversation(self):
        if not self.conversation:
            return
        self.conversation['transcript'] = self.transcript.get('1.0', 'end-1c')
        self.conversation['messages'] = list(self.history)
        self.conversation['draft'] = self.input.get('1.0', 'end-1c')
        try:
            save_record(self.conversation)
            self.refresh_conversations()
        except OSError as error:
            self.status.set('對話儲存失敗：'+str(error))

    def select_conversation(self, event=None):
        if getattr(self, '_listing', False) or self.busy or self.pdf_job:
            return
        selection = self.conversation_list.curselection()
        if not selection:
            return
        item = self.conversation_index[selection[0]]
        if self.conversation and item['id'] == self.conversation['id']:
            return
        self.persist_conversation()
        try:
            record = load_record(item['id'])
            if 'display_turns' not in record:
                from opti_ui import legacy_display_turns
                record['display_turns'] = legacy_display_turns(record)
            self.clear_image()
            self.conversation = record
            self.history = [m for m in record.get('messages', []) if m.get('role') in ('user', 'assistant')][-6:]
            self.last_answer = next((m.get('content', '') for m in reversed(self.history)
                                     if m.get('role') == 'assistant'), '')
            self.photos.clear()
            self.transcript.configure(state='normal')
            self.transcript.delete('1.0', 'end')
            self.transcript.insert('end', record.get('transcript', ''))
            self.transcript.configure(state='disabled')
            self.input.delete('1.0', 'end')
            self.input.insert('1.0', record.get('draft', ''))
            self.refresh_conversations()
            from opti_ui import render_turns
            render_turns(self)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.set('無法開啟對話：'+str(error))

    def rename_conversation(self, event=None):
        selection = self.conversation_list.curselection()
        if self.busy or not selection:
            return 'break'
        record = self.conversation_index[selection[0]]
        name = simpledialog.askstring('重新命名對話', '對話標題：', initialvalue=record['title'], parent=self.root)
        if name is not None and name.strip():
            name = name.strip()[:100]
            if self.conversation and self.conversation['id'] == record['id']:
                self.conversation['title'] = name
                self.persist_conversation()
            else:
                record['title'] = name
                try:
                    save_record(record)
                    self.refresh_conversations()
                except OSError as error:
                    self.status.set('標題儲存失敗：'+str(error))
        return 'break'

    def delete_conversation(self, identifier):
        if self.busy or self.pdf_job:
            return
        record = next((item for item in self.conversation_index if item['id'] == identifier), None)
        if record is None:
            return
        if not messagebox.askyesno('刪除對話',
                                   '確定要刪除「'+record.get('title', '未命名對話')+'」嗎？\n此操作無法復原。',
                                   parent=self.root):
            return
        try:
            delete_record(identifier)
        except OSError as error:
            self.status.set('刪除對話失敗：'+str(error))
            return
        if self.conversation and self.conversation['id'] == identifier:
            self.cancel_pdf_job()
            self.conversation = None
            super().new_chat()
            self.input.delete('1.0', 'end')
            from opti_ui import render_turns
            render_turns(self)
        self.refresh_conversations()
        self.status.set('已刪除對話')

    def new_chat(self):
        if self.busy:
            return
        self.persist_conversation()
        self.cancel_pdf_job()
        self.conversation = None
        super().new_chat()
        self.refresh_conversations()
        from opti_ui import render_turns
        render_turns(self)

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
        self.root.after(650, lambda chosen=theme: self.set_titlebar_theme(chosen))
        from opti_ui import paint_roles, refresh_toolbar_icons
        paint_roles(self, theme)
        refresh_toolbar_icons(self, theme)
        self.transcript.configure(bg=p['paper'], fg=p['ink'])
        style = ttk.Style(self.root)
        style.configure('.', font=(self.ui_font, 10), background=p['bg'], foreground=p['ink'])
        style.configure('TButton', padding=(10, 7), background=p['panel'], foreground=p['ink'], borderwidth=0)
        style.map('TButton', background=[('active', p['selected'])], foreground=[('disabled', p['muted'])])
        style.configure('Outline.TButton', padding=(10, 8), background=p['panel'], foreground=p['ink'], borderwidth=1,
                        bordercolor=p['line'], relief='flat')
        style.map('Outline.TButton', background=[('active', p['selected'])])
        style.configure('Primary.TButton', padding=(11, 8), background=p['selected'], foreground=p['ink'],
                        borderwidth=1, bordercolor=p['accent'], relief='flat')
        style.map('Primary.TButton', background=[('active', p['accent'])], foreground=[('active', p['bg'])])
        style.configure('Icon.TButton', padding=(5, 5), background=p['panel'], borderwidth=0)
        style.map('Icon.TButton', background=[('active', p['selected'])])
        style.configure('Accent.TButton', background=p['accent'], foreground=p['bg'])
        style.configure('TEntry', fieldbackground=p['paper'], foreground=p['ink'], insertcolor=p['ink'])
        style.configure('TCombobox', fieldbackground=p['paper'], foreground=p['ink'], arrowcolor=p['ink'])
        style.map('TCombobox', fieldbackground=[('readonly', p['paper'])], foreground=[('readonly', p['ink'])])
        style.configure('TNotebook.Tab', padding=(14, 8))
        style.map('TNotebook.Tab', background=[('selected', p['paper'])])
        self.style_scrollbars(style, theme, p)
        self.root.option_add('*TCombobox*Listbox.background', p['paper'])
        self.root.option_add('*TCombobox*Listbox.foreground', p['ink'])
        for tag, color in [('user', 'accent'), ('assistant', 'gold'), ('note', 'muted')]:
            self.transcript.tag_configure(tag, foreground=p[color], font=(self.ui_font, 10, 'bold' if tag != 'note' else 'normal'))
        self.transcript.tag_configure('error', foreground='#E57373' if theme == 'dark' else '#A23F3F')
        logo = Image.open(ASSETS/'logo-teal.png').convert('RGBA')
        logo.thumbnail((52, 38), Image.Resampling.LANCZOS)
        self.logo_photo = ImageTk.PhotoImage(logo)
        self.logo.configure(image=self.logo_photo)
        self.conversation_list.configure(bg=p['panel'], fg=p['ink'], selectbackground=p['selected'], selectforeground=p['ink'])
        self.history_context_menu.configure(bg=p['panel'], fg=p['ink'], activebackground=p['selected'],
                                            activeforeground=p['ink'], font=(self.ui_font, 10))
        self.refresh_conversations()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.apply_theme(theme)
        if self.about_window and self.about_window.winfo_exists():
            self.about_window.apply_theme(theme)

    def set_titlebar_theme(self, theme, window=None):
        window = window or self.root
        if self.closed or not window.winfo_exists():
            return
        try:
            dark = ctypes.c_int(theme == 'dark')
            ctypes.windll.user32.GetParent.argtypes = [ctypes.c_void_p]
            ctypes.windll.user32.GetParent.restype = ctypes.c_void_p
            child = ctypes.c_void_p(window.winfo_id())
            hwnd = ctypes.windll.user32.GetParent(child) or child.value
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), 20,
                ctypes.byref(dark), ctypes.sizeof(dark))
        except (AttributeError, OSError):
            pass

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
            catalog = initialize_models(self.model_download,
                lambda event: self.events.put(('model_progress', event)), ensure_default=self.first_setup)
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

    def configure_drop(self):
        try:
            from tkinterdnd2 import DND_FILES, TkinterDnD
            TkinterDnD.require(self.root)
            for widget in (self.root,):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind('<<Drop>>', self.on_drop)
        except Exception as error:
            self.status.set('拖放無法啟用：'+str(error)+' · 可使用 + 選檔')

    def on_drop(self, event):
        paths = self.root.tk.splitlist(event.data)
        if len(paths) != 1:
            self.status.set('一次請拖入一個檔案。')
        else:
            self.attach_file(paths[0])
        return 'copy'

    def choose_file(self):
        if self.busy or self.closed:
            return
        filename = filedialog.askopenfilename(parent=self.root, title='加入對話附件',
            filetypes=[('PDF 或圖片', '*.pdf *.png *.jpg *.jpeg *.webp *.bmp'), ('所有檔案', '*.*')])
        if filename:
            self.attach_file(filename)

    def attach_file(self, filename):
        if self.busy or self.closed:
            self.status.set('請等待目前回覆完成。')
            return
        path = Path(filename)
        if path.suffix.lower() == '.pdf':
            self.load_pdf(path)
        elif path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'):
            self.attach_image(path)
            if self.pending_path == path:
                self.status.set('圖片已附加 · 輸入問題後按傳送')
        else:
            self.status.set('目前支援 PDF、PNG、JPG、WEBP、BMP。')

    def load_pdf(self, filename):
        try:
            _, size = inspect_pdf(filename)
        except Exception as error:
            self.status.set(str(error))
            return
        self.cancel_pdf_job()
        cancelled = threading.Event()
        self.pdf_job = cancelled
        self.status.set(f'正在解析 PDF · {size/1024**2:.2f} MB…')
        def work():
            try:
                result = prepare_pdf(filename,
                    lambda note: self.extra.put(('pdf_progress', (cancelled, note))), cancelled)
                self.extra.put(('pdf_ready', (cancelled, result)))
            except InterruptedError:
                pass
            except Exception as error:
                self.extra.put(('pdf_error', (cancelled, str(error))))
        threading.Thread(target=work, daemon=True).start()

    def cancel_pdf_job(self):
        if self.pdf_job:
            self.pdf_job.set()
            self.pdf_job = None

    def open_pdf_page(self):
        if self.pdf_source and not self.busy and not self.pdf_job:
            PdfPicker(self.root, self.pdf_source['path'], self.attach_pdf, self.pdf_source)

    def attach_image(self, filename):
        previous = self.pending_path
        try:
            _, thumbnail = prepare_image(filename, fast=True)
            history_thumbnail = thumbnail.copy()
            history_thumbnail.thumbnail((220, 150), Image.Resampling.LANCZOS)
            thumbnail.thumbnail((128, 84), Image.Resampling.LANCZOS)
            preview = ImageTk.PhotoImage(thumbnail, master=self.root)
            self.cancel_pdf_job()
            self.pending_path = Path(filename)
            self.pending_thumbnail = history_thumbnail
            self.preview = preview
            self.preview_image.configure(image=preview)
            self.preview_label.configure(text='圖片 · '+self.pending_path.name)
            self.remove_button.configure(state='normal')
            from opti_ui import show_attachment
            show_attachment(self)
            self.remove_capture_file(previous)
            self.pending_document = None
            self.pdf_image_note = ''
            self.pdf_source = None
            self.page_button.configure(state='disabled')
            self.route.set('自動分流')
        except Exception as error:
            messagebox.showerror('無法開啟圖片', str(error), parent=self.root)

    def choose_pdf(self):
        if self.busy or self.closed:
            return
        filename = filedialog.askopenfilename(parent=self.root, title='選擇 PDF', filetypes=[('PDF 文件', '*.pdf')])
        if filename:
            self.load_pdf(filename)

    def attach_pdf(self, document, image=None, page=None):
        if self.closed:
            return
        self.pdf_source = document
        if image is not None:
            path = None
            try:
                with tempfile.NamedTemporaryFile(prefix='OptiChat-pdf-', suffix='.jpg', delete=False) as stream:
                    path = Path(stream.name)
                self.capture_files.add(path)
                image.save(path, format='JPEG', quality=82, optimize=True)
                self.attach_image(path)
                if self.pending_path != path:
                    self.remove_capture_file(path)
                    return
                self.pdf_image_note = f"PDF：{document['path'].name} · 第 {page}／{document['pages']} 頁"
                self.image_name.configure(text=self.pdf_image_note)
                self.pdf_source = document
                self.page_button.configure(state='normal')
                from opti_ui import show_attachment
                show_attachment(self, pdf=True)
                self.route.set('自動分流')
                self.fast.set(False)
                self.status.set('PDF 頁面已附加 · 輸入問題後按傳送')
            except Exception as error:
                self.remove_capture_file(path)
                messagebox.showerror('無法附加 PDF', str(error), parent=self.root)
            return
        if not document['text']:
            return
        self.clear_image()
        self.pending_document = document
        self.page_button.configure(state='normal')
        self.route.set('純文字')
        self.preview_label.configure(image='', text=f"PDF · {document['pages']} 頁 · 文字已擷取")
        self.image_name.configure(text=document['path'].name)
        self.remove_button.configure(state='normal')
        from opti_ui import show_attachment
        show_attachment(self, pdf=True)
        _, label = pdf_prompt(document, '', self.settings['text'])
        self.status.set(label+' · 尚未傳送')

    def has_attachment(self):
        return bool(self.pending_document) or super().has_attachment()

    def default_prompt(self):
        return '請摘要這份 PDF 的內容。' if self.pending_document else super().default_prompt()

    def prepare_turn(self, text):
        if self.pending_document:
            kind = 'vision' if self.route_mode() == 'vision' else 'text'
            content, _ = pdf_prompt(self.pending_document, text, self.settings[kind])
            return {'role': 'user', 'content': content}
        if self.pdf_image_note:
            text += '\n'+self.pdf_image_note+'（只附加此頁）'
        return super().prepare_turn(text)

    def write_attachment_note(self):
        if self.pending_document:
            kind = 'vision' if self.route_mode() == 'vision' else 'text'
            _, label = pdf_prompt(self.pending_document, '', self.settings[kind])
            self.write(label+'\n', 'note')
        elif self.pdf_image_note:
            self.write(self.pdf_image_note+'\n', 'note')

    def clear_image(self):
        self.cancel_pdf_job()
        previous = self.pending_path
        self.pending_path = None
        self.pending_thumbnail = None
        self.preview = None
        self.preview_image.configure(image='')
        self.preview_label.configure(image='', text='', width=0, height=1)
        self.remove_button.configure(state='disabled')
        self.remove_capture_file(previous)
        self.pending_document = None
        self.pdf_image_note = ''
        self.pdf_source = None
        self.page_button.configure(state='disabled')
        from opti_ui import hide_attachment
        hide_attachment(self)

    def set_busy(self, busy):
        super().set_busy(busy)
        self.capture_button.configure(state='disabled' if busy or self.capture_session else 'normal')

    def refresh_models(self):
        if self.model_loading or self.busy or self.speech_job or self.catalog_download_job:
            return
        self.model_loading = True
        self.ready = False
        self.model_download = ModelDownload()
        self.send_button.configure(state='disabled')
        self.stop_button.configure(text='停止初始化', state='normal')
        self.status.set('正在檢查本機模型…')
        threading.Thread(target=self.connect, daemon=True).start()

    def update_catalog_download_ui(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.set_download_state(self.catalog_download_job is not None,
                self.catalog_download_status, self.catalog_download_percent)

    def start_catalog_download(self, name):
        try:
            name = validate_model_name(name)
        except ValueError as error:
            self.catalog_download_status = str(error)
            self.update_catalog_download_ui()
            return False
        if self.catalog_download_job:
            self.catalog_download_status = '已有模型正在下載；請先等待或取消。'
            self.update_catalog_download_ui()
            return False
        if self.model_loading or self.busy or self.speech_job:
            self.catalog_download_status = '請先等待目前的模型初始化或回覆完成。'
            self.update_catalog_download_ui()
            return False
        job = ModelDownload(name)
        self.catalog_download_job = job
        self.catalog_download_status = f'正在準備下載 {name}…'
        self.catalog_download_percent = 0
        self.update_catalog_download_ui()
        threading.Thread(target=self.download_catalog_model, args=(job,), daemon=True).start()
        return True

    def download_catalog_model(self, job):
        try:
            ensure_model_service('text', 'CPU')
            job.pull(lambda event: self.extra.put(('catalog_pull_progress', (job, event))))
            catalog = installed_models()
            expected = {job.model}
            if ':' not in job.model:
                expected.add(job.model+':latest')
            if not any(item['name'] in expected for item in catalog):
                raise RuntimeError('下載結束，但重新整理清單後找不到這個模型。')
            self.extra.put(('catalog_pull_ready', (job, catalog)))
        except Exception as error:
            self.extra.put(('catalog_pull_error', (job, str(error))))

    def stop_catalog_download(self):
        if self.catalog_download_job:
            self.catalog_download_job.cancel()
            self.catalog_download_status = '正在取消模型下載…'
            self.update_catalog_download_ui()

    def accept_model_catalog(self, catalog):
        self.catalog = catalog
        updated = select_installed_defaults(self.settings, catalog)
        try:
            if not self.config_error and (updated != self.settings or not (DATA/'settings.json').exists()):
                save_settings(updated)
        except Exception as error:
            self.write('預設模型設定無法保存：'+str(error)+'\n', 'error')
        self.settings = updated
        self.catalog_loaded = True
        if not self.ready and model_choices(catalog, 'text'):
            self.model_loading = False
            self.ready = True
            self.stop_button.configure(text='停止回覆')
            self.set_busy(False)
            self.apply_theme()
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.set_models(catalog)

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
        from opti_ui import short_model_name
        return short_model_name(self.settings[kind]['model'])

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
        if not self.ready or self.model_loading or self.busy:
            return
        if self.pdf_job:
            self.status.set('請等待 PDF 解析完成。')
            return
        if self.speech_job:
            self.status.set('請先停止或等待語音生成完成。')
            return
        if self.route_mode() == 'text' and self.pending_path:
            self.route.set('自動分流')
        question = self.input.get('1.0', 'end-1c').strip() or (self.default_prompt() if self.has_attachment() else '')
        if not question:
            return
        attachment = ''
        if self.pending_document:
            _, attachment = pdf_prompt(self.pending_document, '', self.settings['text'])
        elif self.pdf_image_note:
            attachment = self.pdf_image_note
        elif self.pending_path:
            attachment = '圖片：'+self.pending_path.name
        thumbnail = self.pending_thumbnail if self.pending_path and not self.pdf_image_note else None
        pending = {'role': 'user', 'content': ''}
        if self.pending_path:
            pending['images'] = ['pending']
        kind, *_ = route_messages(self.settings, build_messages(self.history, pending), self.route_mode(), self.catalog)
        if self.settings[kind]['model'] not in model_choices(self.catalog, kind):
            self.status.set('目前選取的模型未安裝或不支援此功能，請在設定重新選擇。')
            return
        attachment_kind = 'pdf' if self.pending_document or self.pdf_image_note else 'image' if self.pending_path else None
        source = ((self.pending_document or self.pdf_source)['path'] if attachment_kind == 'pdf'
                  else self.pending_path if attachment_kind == 'image' else None)
        created_conversation = self.conversation is None
        if created_conversation:
            self.conversation = new_record()
        turns = self.conversation.setdefault('display_turns', [])
        saved_file = None
        if source is not None:
            try:
                saved_file = save_attachment(self.conversation['id'], len(turns), source, attachment_kind)
            except (OSError, ValueError) as error:
                messagebox.showerror('無法儲存附件', str(error), parent=self.root)
                if created_conversation:
                    self.conversation = None
                return
        was_busy = self.busy
        self._visual_error = None
        super().send()
        if not was_busy and self.busy:
            record = {'time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                      'question': question, 'attachment': attachment,
                      'model': self.settings[self.active_kind]['model']+' · '+self.active_device,
                      'answer': ''}
            if saved_file is not None:
                record['attachment_kind'] = attachment_kind
            if thumbnail is not None:
                try:
                    save_preview(self.conversation['id'], len(turns), thumbnail)
                    record['preview'] = True
                except OSError:
                    pass
            turns.append(record)
            from opti_ui import add_turn
            add_turn(self, record, len(turns)-1)
            self.persist_conversation()
        else:
            if saved_file is not None:
                saved_file.unlink(missing_ok=True)
            if created_conversation:
                self.conversation = None

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
                    self.model_loading = False
                    self.accept_model_catalog(value)
                    self.status.set(f'● 已就緒 · 已安裝 {len(value)} 個模型')
                elif kind == 'models_error':
                    self.model_loading = False
                    self.status.set('模型初始化未完成 · 請到「設定 → 聊天模型」重新整理')
                    self.stop_button.configure(text='停止回覆', state='disabled')
                    self.write('\n模型：'+value+'\n', 'error')
                elif kind == 'token':
                    self.answer += value
                    self.write(value)
                    if self.visual_answer_var:
                        self.visual_answer_var.set(self.answer)
                elif kind == 'complete':
                    self.history.extend([self.turn, {'role': 'assistant', 'content': self.answer}])
                    self.history = self.history[-6:]
                    self.last_answer = self.answer
                    self.completed_turn = True
                    if value == 'length':
                        self.write('\n（已達長度上限，可輸入「請繼續」。）', 'note')
                elif kind == 'error':
                    self.write('\n回覆失敗：'+value+'\n', 'error')
                    self._visual_error = value
                    if self.visual_answer_var:
                        self.visual_answer_var.set('回覆失敗：'+value)
                    self.completed_turn = False
                elif kind == 'finished':
                    if value:
                        self.write('\n（已停止，未加入後續對話。）', 'note')
                    self.write('\n\n')
                    self.status.set(f'● {self.active_kind} / {self.active_device} · {int(time.monotonic()-self.started)} 秒')
                    self.set_busy(False)
                    self.request = None
                    if self.conversation and self.conversation.get('display_turns'):
                        current = self.conversation['display_turns'][-1]
                        current['answer'] = self.answer or ('回覆失敗：'+self._visual_error if self._visual_error else
                                                            '已停止。' if value else '未取得回覆。')
                        if self.visual_answer_var:
                            self.visual_answer_var.set(current['answer'])
                        from opti_ui import render_turns
                        render_turns(self)
                    self.persist_conversation()
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
            icon = app_icon(256, '#102330')
            def action(name):
                return lambda *_: self.extra.put((name, None))
            self.tray_icon = pystray.Icon('OptiChat', icon, 'OptiChat · 本機 AI', pystray.Menu(
                pystray.MenuItem('開啟 OptiChat', action('show'), default=True),
                pystray.MenuItem('設定', action('settings')),
                pystray.MenuItem('結束程式', action('quit'))))
            def ready(tray):
                try:
                    tray.visible = True
                    self.extra.put(('tray_ready', None))
                except Exception as error:
                    self.extra.put(('tray_error', str(error)))
            self.tray_icon.run_detached(setup=ready)
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
                    self.status.set('系統匣啟動失敗；關閉視窗將留在工作列：'+str(value))
                elif kind == 'tray_ready':
                    self.tray_unavailable_warned = False
                elif kind == 'pdf_progress':
                    job, note = value
                    if self.pdf_job is job and not job.is_set():
                        self.status.set(note)
                elif kind == 'pdf_ready':
                    job, result = value
                    if self.pdf_job is job and not job.is_set():
                        self.pdf_job = None
                        self.attach_pdf(*result)
                        self.input.focus_set()
                elif kind == 'pdf_error':
                    job, detail = value
                    if self.pdf_job is job and not job.is_set():
                        self.pdf_job = None
                        self.status.set('PDF 無法解析：'+detail)
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
                elif kind == 'catalog_pull_progress':
                    job, event = value
                    if self.catalog_download_job is not job:
                        continue
                    total, completed = event.get('total') or 0, event.get('completed') or 0
                    if event.get('status') == 'success':
                        self.catalog_download_status = f'{job.model} 下載完成，正在更新模型清單…'
                    elif isinstance(total, (int, float)) and total > 0 and isinstance(completed, (int, float)):
                        self.catalog_download_percent = max(0, min(100, round(completed / total * 100)))
                        self.catalog_download_status = (f'{job.model} · 目前檔案 {self.catalog_download_percent}% · '
                            f'{completed/1024**3:.2f}/{total/1024**3:.2f} GiB')
                    else:
                        self.catalog_download_status = f'{job.model} · {event.get("status", "正在下載…")}'
                    self.update_catalog_download_ui()
                elif kind == 'catalog_pull_ready':
                    job, catalog = value
                    if self.catalog_download_job is not job:
                        continue
                    self.catalog_download_job = None
                    self.catalog_download_percent = 100
                    self.accept_model_catalog(catalog)
                    self.catalog_download_status = f'{job.model} 已下載；可到「聊天模型」選擇。'
                    self.status.set(self.catalog_download_status)
                    self.update_catalog_download_ui()
                elif kind == 'catalog_pull_error':
                    job, detail = value
                    if self.catalog_download_job is not job:
                        continue
                    self.catalog_download_job = None
                    self.catalog_download_status = ('模型下載已取消。' if job.cancelled.is_set()
                        else '模型下載失敗：'+detail)
                    self.status.set(self.catalog_download_status)
                    self.update_catalog_download_ui()
                elif kind == 'update':
                    self.update_busy = False
                    self.update_status.set(value)
                    if '已下載' in value:
                        self.status.set(value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll_extra)

    def check_updates(self, force=False):
        if not force and not self.closed:
            self.root.after(15 * 60 * 1000, self.check_updates)
        if self.closed or self.update_busy:
            return
        error_file = UPDATE_DIR/'last-error.txt'
        if not force and error_file.exists():
            self.update_status.set('上次更新檢查：'+error_file.read_text(encoding='utf-8'))
        self.update_busy = True
        self.update_status.set('正在檢查更新…')
        def run():
            try:
                result = check_for_update(force=True)
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

    def open_about(self):
        if self.about_window and self.about_window.winfo_exists():
            self.about_window.lift()
            return
        self.about_window = AboutWindow(self)
        self.about_window.apply_theme(self.last_theme or self.resolved_theme())

    def show(self):
        if self.capture_session:
            self.capture_session.cancel()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def close(self):
        if self.settings['tray']:
            if self.tray_icon and self.tray_icon.visible:
                if not self.tray_hint_shown:
                    self.tray_hint_shown = True
                    messagebox.showinfo('OptiChat 常駐中',
                                        'OptiChat 會留在右下角系統匣。\n若看不到圖示，請按「^」展開隱藏圖示；可將 OptiChat 圖示拖到通知區。',
                                        parent=self.root)
                if self.settings_window and self.settings_window.winfo_exists():
                    self.settings_window.destroy()
                self.root.withdraw()
            else:
                if not self.tray_unavailable_warned:
                    self.tray_unavailable_warned = True
                    messagebox.showwarning('系統匣尚未顯示',
                                           'OptiChat 圖示尚未出現在系統匣。視窗會留在工作列，方便重新開啟。',
                                           parent=self.root)
                self.root.iconify()
        else:
            self.quit()

    def quit(self):
        if not self.closed:
            self.persist_conversation()
        self.cancel_pdf_job()
        self.shutdown.set()
        if self.capture_session:
            self.capture_session.cancel()
        for path in tuple(self.capture_files):
            self.remove_capture_file(path)
        self.model_download.cancel()
        if self.catalog_download_job:
            self.catalog_download_job.cancel()
        self.stop_speech()
        if self.tray_icon:
            self.tray_icon.stop()
        if (not self.update_on_exit_started and (UPDATE_DIR/'pending.json').is_file()
                and Path(__file__).with_name('package-files.json').is_file()):
            self.update_on_exit_started = True
            try:
                subprocess.Popen([sys.executable, str(Path(__file__).with_name('opti_bootstrap.py')), '--apply-only'],
                                 cwd=Path(__file__).resolve().parent, creationflags=subprocess.CREATE_NO_WINDOW)
            except OSError as error:
                (UPDATE_DIR/'last-error.txt').write_text('離開時更新啟動失敗：'+str(error), encoding='utf-8')
        super().close()


class AboutWindow(tk.Toplevel):
    SITE_URL = 'https://optiimind.com/'
    DOWNLOAD_URL = 'https://optiimind.com/Tools/optiichat/#download'

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('關於 OptiChat')
        self.resizable(False, False)
        self.transient(app.root)
        self.body = tk.Frame(self, padx=28, pady=22)
        self.body.pack(fill='both', expand=True)
        self.heading = tk.Label(self.body, text='OptiChat', font=(app.ui_font, 19, 'bold'), anchor='w')
        self.heading.pack(anchor='w')
        self.version = tk.Label(self.body, text='版本 '+VERSION+' · Optiimind', font=(app.ui_font, 10))
        self.version.pack(anchor='w', pady=(5, 18))
        self.site_button = ttk.Button(self.body, text='開啟官網  ↗', style='Outline.TButton',
                                      command=lambda: webbrowser.open(self.SITE_URL))
        self.site_button.pack(fill='x', pady=(0, 8))
        self.download_button = ttk.Button(self.body, text='下載 OptiChat  ↗', style='Primary.TButton',
                                          command=lambda: webbrowser.open(self.DOWNLOAD_URL))
        self.download_button.pack(fill='x')
        self.close_button = ttk.Button(self.body, text='關閉', command=self.destroy)
        self.close_button.pack(anchor='e', pady=(20, 0))
        self.center_on_parent()

    def center_on_parent(self):
        parent = self.app.root
        parent.update_idletasks()
        width, height = 420, 260
        x = parent.winfo_rootx()+(parent.winfo_width()-width)//2
        y = parent.winfo_rooty()+(parent.winfo_height()-height)//2
        screen_x, screen_y = self.winfo_vrootx(), self.winfo_vrooty()
        x = max(screen_x, min(x, screen_x+self.winfo_vrootwidth()-width))
        y = max(screen_y, min(y, screen_y+self.winfo_vrootheight()-height))
        self.geometry(f'{width}x{height}+{x}+{y}')

    def apply_theme(self, theme):
        p = DARK if theme == 'dark' else LIGHT
        self.configure(bg=p['bg'])
        self.body.configure(bg=p['panel'])
        self.heading.configure(bg=p['panel'], fg=p['ink'])
        self.version.configure(bg=p['panel'], fg=p['muted'])
        self.app.root.after(100, lambda chosen=theme: self.app.set_titlebar_theme(chosen, self))


class SettingsWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title('OptiChat 設定')
        self.minsize(720, 600)
        self.transient(app.root)
        self.vars = {}
        self.tab_canvases = {}
        self.tab_scrollbars = {}
        self.native_voices = []
        controls = ttk.Frame(self, padding=12, style='SettingsFooter.TFrame')
        controls.pack(side='bottom', fill='x')
        ttk.Button(controls, text='儲存設定', style='SettingsAccent.TButton', command=self.save).pack(side='right')
        ttk.Button(controls, text='取消', style='Settings.TButton', command=self.destroy).pack(side='right', padx=8)
        self.notice = tk.StringVar(value='設定儲存後，下次生成時生效。')
        ttk.Label(controls, textvariable=self.notice, style='SettingsFooter.TLabel').pack(side='left')
        notebook = ttk.Notebook(self, style='Settings.TNotebook')
        notebook.pack(fill='both', expand=True, padx=14, pady=14)
        general = self.tab(notebook, '外觀與常駐')
        self.field(general, '主題', 'theme', ['system', 'light', 'dark'])
        self.note(general, 'system 跟隨 Windows；light 亮色；dark 暗色。')
        self.check(general, '關閉視窗時收至右下角系統匣', 'tray')
        self.check(general, '模型完成回覆後自動朗讀', 'auto_speak')
        self.check(general, '預設快速圖片模式（560 px）', 'fast_image')
        self.note(general, '每次啟動都從 R2 檢查更新；有新版會先驗證並套用。\n離線時仍可使用目前版本，連線恢復後會重試。系統匣「結束程式」也會套用已下載更新。')
        ttk.Label(general, textvariable=app.update_status, wraplength=680,
                  style='SettingsMuted.TLabel').pack(anchor='w', pady=8)
        ttk.Button(general, text='立即檢查更新', style='Settings.TButton',
                   command=lambda: app.check_updates(True)).pack(anchor='w')
        self.note(general, '系統匣右鍵可開啟設定或結束程式。\n聊天紀錄儲存在本機，不會因結束程式而清除。\nCPU／GPU 數值是整台電腦的即時使用率。\n\n介面與原始標誌取自 optiimind.com，為你的本機工具。')
        models = self.tab(notebook, '聊天模型')
        self.model_combos = {}
        self.model_notice = tk.StringVar(value='讀取已安裝模型中…')
        ttk.Button(models, text='重新整理已安裝模型', style='Settings.TButton',
                   command=self.app.refresh_models).pack(anchor='e')
        ttk.Label(models, textvariable=self.model_notice, wraplength=700,
                  style='SettingsMuted.TLabel').pack(anchor='w', pady=6)
        for key, title in [('text', '文字聊天模型'), ('vision', '圖片理解模型')]:
            box = ttk.LabelFrame(models, text=title, padding=12, style='Settings.TLabelframe')
            box.pack(fill='x', pady=8)
            self.model_combos[key] = self.field(box, '已安裝模型', key+'.model', [])
            self.field(box, '運算裝置', key+'.device', ['CPU', 'GPU'])
            self.field(box, 'GPU 層數（-1 自動）', key+'.gpu_layers')
            self.field(box, 'Context / 上下文長度', key+'.context')
            self.field(box, '最多輸出 tokens', key+'.max_tokens')
            self.field(box, 'Temperature（0～2）', key+'.temperature')
        self.note(models, '文字選單列出聊天模型；圖片選單只列出支援看圖的模型。\n首次使用若缺少預設模型，會自動從 Ollama 官方下載 llama3.2-vision。\nCPU 強制 num_gpu=0；GPU 依層數卸載，部分運算仍可能使用 RAM。\nLlama 3.2 Vision 使用相容服務；其他模型使用一般 Ollama。')
        downloads = self.tab(notebook, '下載模型')
        self.note(downloads, '在 Ollama 模型庫找到想用的模型名稱，貼在這裡下載。\n模型可能佔數 GB，請先查看模型頁的大小與需求。')
        ttk.Button(downloads, text='瀏覽 Ollama 模型庫  ↗', style='Settings.TButton',
                   command=lambda: webbrowser.open('https://ollama.com/search')).pack(anchor='w', pady=(0, 16))
        download_row = ttk.Frame(downloads, style='SettingsPage.TFrame')
        download_row.pack(fill='x', pady=4)
        ttk.Label(download_row, text='模型名稱', width=24, style='Settings.TLabel').pack(side='left')
        self.download_model = tk.StringVar(self, value='llama3.2-vision')
        self.download_entry = ttk.Entry(download_row, textvariable=self.download_model,
                                        style='Settings.TEntry')
        self.download_entry.pack(side='left', fill='x', expand=True)
        self.download_entry.bind('<Return>', lambda _: self.start_model_download())
        download_actions = ttk.Frame(downloads, style='SettingsPage.TFrame')
        download_actions.pack(fill='x', pady=(12, 8))
        self.download_button = ttk.Button(download_actions, text='下載模型',
                                          style='SettingsAccent.TButton', command=self.start_model_download)
        self.download_button.pack(side='left')
        self.cancel_download_button = ttk.Button(download_actions, text='取消下載',
                                                 style='Settings.TButton', command=app.stop_catalog_download)
        self.cancel_download_button.pack(side='left', padx=8)
        self.download_progress = ttk.Progressbar(downloads, maximum=100, mode='determinate',
                                                style='Settings.Horizontal.TProgressbar')
        self.download_progress.pack(fill='x', pady=(5, 8))
        self.download_status = tk.StringVar(self)
        ttk.Label(downloads, textvariable=self.download_status, wraplength=700,
                  style='SettingsMuted.TLabel').pack(anchor='w')
        self.note(downloads, '完成後到「聊天模型」分頁，從文字或圖片模型下拉選單選擇。\n只支援 embedding 的模型不會出現在聊天選單。')
        speech = self.tab(notebook, '語音')
        self.provider_combo = provider = self.field(speech, '語音引擎', 'speech.provider',
                                                   ['windows', 'breeze'] if app.breeze_available else ['windows'])
        provider.bind('<<ComboboxSelected>>', lambda _: self.provider_changed())
        self.device_widget = self.field(speech, '語音運算裝置', 'speech.device', ['CPU', 'GPU'])
        self.device_widget.configure(state='disabled')
        self.note(speech, 'Windows 使用 CPU，可直接朗讀，不需另外下載語音模型。')
        self.native_box = ttk.LabelFrame(speech, text='Windows 本機語音', padding=10,
                                         style='Settings.TLabelframe')
        self.native_box.pack(fill='x', pady=8)
        self.voice_combo = self.field(self.native_box, '已安裝聲音', 'speech.voice_id', [''])
        self.field(self.native_box, '語速（80～350）', 'speech.rate')
        self.field(self.native_box, '音量（0～1）', 'speech.volume')
        self.breeze_box = None
        if app.breeze_available:
            self.breeze_box = ttk.LabelFrame(speech, text='Breeze-TTS-2', padding=10,
                                             style='Settings.TLabelframe')
            self.breeze_box.pack(fill='x', pady=8)
            self.field(self.breeze_box, '服務網址', 'speech.endpoint')
            ttk.Button(self.breeze_box, text='測試服務 / health', style='Settings.TButton',
                       command=self.health).pack(anchor='e')
            self.field(self.breeze_box, 'Voice Design / Clone', 'speech.mode', ['design', 'clone'])
            self.field(self.breeze_box, '聲音描述 / Direction', 'speech.instruction')
            self.field(self.breeze_box, 'Clone 參考音檔', 'speech.ref_audio')
            ttk.Button(self.breeze_box, text='選擇參考音檔', style='Settings.TButton',
                       command=self.choose_reference).pack(anchor='e')
            self.field(self.breeze_box, '音檔正確逐字稿', 'speech.ref_text')
            self.field(self.breeze_box, 'CFG Scale（>0）', 'speech.cfg_scale')
            self.field(self.breeze_box, 'Seed', 'speech.seed')
            self.note(speech, 'design：以描述設計聲音；clone：需音檔及逐字稿，可加 Direction。\nBreeze 會將文字與參考音檔傳至所填服務；Windows 不使用這些參數。')
            advanced = self.tab(notebook, 'Breeze 服務參數')
            self.note(advanced, '以下是官方服務啟動參數，需要在服務端重啟才生效。\n儲存設定只保存選項，不會遠端更改已執行的服務。')
            for key in ['fast_all', 'fast_text_encoder', 'fast_backbone_prefill', 'fast_backbone_decode', 'fast_depth_decoder', 'fast_codec']:
                self.check(advanced, '--'+key.replace('_', '-'), 'speech.'+key)
            ttk.Button(advanced, text='複製服務啟動命令', style='Settings.TButton',
                       command=self.copy_command).pack(anchor='w', pady=14)
            self.note(advanced, '將命令中的 PATH_TO_BREEZE_TTS_2 替換成模型目錄。\n預設 eager 約需 7.7 GiB，建議 12 GB GPU；fast-all 建議 24 GB。\n\n官方 API 固定值：max_new_tokens=1500、max_seq_len=2048、\nrepetition_penalty=1.1。這些不是可傳入的請求參數。\n輸出格式：24 kHz / mono / 16-bit PCM（本程式封裝為 WAV）。\n\n權重與產出限研究及非商業使用，詳見模型授權。\n完整安裝方式見 OptiiChat-使用說明.md。')
        self.provider_changed()
        self.set_models(app.catalog if app.catalog_loaded else None)
        self.set_download_state(app.catalog_download_job is not None,
                                app.catalog_download_status, app.catalog_download_percent)
        threading.Thread(target=self.load_voices, daemon=True).start()
        self.apply_theme(app.last_theme or app.resolved_theme())
        self.center_on_parent()

    def center_on_parent(self):
        self.app.root.update_idletasks()
        self.update_idletasks()
        screen_x, screen_y = self.winfo_vrootx(), self.winfo_vrooty()
        screen_width, screen_height = self.winfo_vrootwidth(), self.winfo_vrootheight()
        width = min(860, max(720, screen_width-80))
        height = min(790, max(600, screen_height-80))
        parent = self.app.root
        x = parent.winfo_rootx()+(parent.winfo_width()-width)//2
        y = parent.winfo_rooty()+(parent.winfo_height()-height)//2
        x = max(screen_x, min(x, screen_x+screen_width-width))
        y = max(screen_y, min(y, screen_y+screen_height-height))
        self.geometry(f'{width}x{height}+{x}+{y}')

    def apply_theme(self, theme):
        p = DARK if theme == 'dark' else LIGHT
        self.configure(bg=p['bg'])
        style = ttk.Style(self)
        style.configure('SettingsFooter.TFrame', background=p['panel'])
        style.configure('SettingsPage.TFrame', background=p['paper'])
        style.configure('Settings.TLabel', background=p['paper'], foreground=p['ink'])
        style.configure('SettingsMuted.TLabel', background=p['paper'], foreground=p['muted'])
        style.configure('SettingsFooter.TLabel', background=p['panel'], foreground=p['muted'])
        style.configure('Settings.TCheckbutton', background=p['paper'], foreground=p['ink'])
        style.map('Settings.TCheckbutton', background=[('active', p['paper'])],
                  foreground=[('disabled', p['muted'])])
        style.configure('Settings.TLabelframe', background=p['paper'], bordercolor=p['line'])
        style.configure('Settings.TLabelframe.Label', background=p['paper'], foreground=p['accent'],
                        font=(self.app.ui_font, 10, 'bold'))
        style.configure('Settings.TEntry', fieldbackground=p['input'], foreground=p['ink'],
                        insertcolor=p['ink'], bordercolor=p['line'])
        style.configure('Settings.TCombobox', fieldbackground=p['input'], foreground=p['ink'],
                        background=p['panel'], arrowcolor=p['accent'], bordercolor=p['line'])
        style.map('Settings.TCombobox', fieldbackground=[('readonly', p['input'])],
                  foreground=[('readonly', p['ink']), ('disabled', p['muted'])])
        style.configure('Settings.TButton', background=p['panel'], foreground=p['ink'],
                        bordercolor=p['line'], padding=(10, 7), relief='flat')
        style.map('Settings.TButton', background=[('active', p['selected'])])
        style.configure('SettingsAccent.TButton', background=p['accent'], foreground=p['bg'],
                        bordercolor=p['accent'], padding=(12, 7), relief='flat')
        style.map('SettingsAccent.TButton', background=[('active', p['selected'])],
                  foreground=[('active', p['ink'])])
        style.configure('Settings.Horizontal.TProgressbar', troughcolor=p['input'],
                        background=p['accent'], bordercolor=p['line'])
        style.configure('Settings.TNotebook', background=p['bg'], bordercolor=p['line'])
        style.configure('Settings.TNotebook.Tab', background=p['panel'], foreground=p['muted'],
                        padding=(16, 10), bordercolor=p['line'])
        style.map('Settings.TNotebook.Tab', background=[('selected', p['paper']), ('active', p['selected'])],
                  foreground=[('selected', p['accent']), ('active', p['ink'])])
        self.app.root.after(100, lambda chosen=theme: self.app.set_titlebar_theme(chosen, self))

    def tab(self, notebook, title):
        from opti_ui import auto_scrollbar, fit_scroll_region
        outer = ttk.Frame(notebook, style='SettingsPage.TFrame')
        notebook.add(outer, text=title)
        canvas = tk.Canvas(outer, highlightthickness=0)
        self.app.roles.append((canvas, 'paper', None))
        bar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        self.tab_canvases[title] = canvas
        self.tab_scrollbars[title] = bar
        canvas.pack(fill='both', expand=True)
        auto_scrollbar(canvas, bar)
        body = ttk.Frame(canvas, padding=16, style='SettingsPage.TFrame')
        item = canvas.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda _: fit_scroll_region(canvas))
        def resize(event):
            canvas.itemconfigure(item, width=event.width)
            fit_scroll_region(canvas)
        canvas.bind('<Configure>', resize)
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
        row = ttk.Frame(parent, style='SettingsPage.TFrame')
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=title, width=24, style='Settings.TLabel').pack(side='left')
        var = self.variable(key)
        widget = (ttk.Entry(row, textvariable=var, style='Settings.TEntry') if choices is None
                  else ttk.Combobox(row, textvariable=var, values=choices,
                                    state='readonly', style='Settings.TCombobox'))
        widget.pack(side='left', fill='x', expand=True)
        return widget

    def note(self, parent, text):
        ttk.Label(parent, text=text, wraplength=700, justify='left',
                  style='SettingsMuted.TLabel').pack(anchor='w', pady=10)

    def check(self, parent, title, key):
        ttk.Checkbutton(parent, text=title, variable=self.variable(key, True),
                        style='Settings.TCheckbutton').pack(anchor='w', pady=7)

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

    def start_model_download(self):
        self.app.start_catalog_download(self.download_model.get())

    def set_download_state(self, active, status, percent):
        self.download_status.set(status)
        self.download_progress.configure(value=percent)
        self.download_entry.configure(state='disabled' if active else 'normal')
        self.download_button.configure(state='disabled' if active else 'normal')
        self.cancel_download_button.configure(state='normal' if active else 'disabled')

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
