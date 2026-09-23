"""Local, streaming Tkinter chat interface for Llama 3.2 Vision."""
import base64
import asyncio
import io
import json
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk
from start_llama32_vision import HOST, MODEL, ensure_service

BG = '#F4F3EE'
PAPER = '#FFFFFF'
INK = '#243733'
MUTED = '#697B74'
ACCENT = '#246A54'


def prepare_image(path, fast=True):
    """Decode locally; strip metadata and constrain memory before transmission."""
    path = Path(path)
    if path.stat().st_size > 30 * 1024 * 1024:
        raise ValueError('圖片超過 30 MB，請先縮小圖片。')
    with Image.open(path) as original:
        if original.width * original.height > 40_000_000:
            raise ValueError('圖片解析度過大，請先縮小至 4000 萬像素以內。')
        image = ImageOps.exif_transpose(original).convert('RGBA')
        background = Image.new('RGBA', image.size, 'white')
        image = Image.alpha_composite(background, image).convert('RGB')
        image.thumbnail((560, 560) if fast else (1120, 1120), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    if path.suffix.lower() in ('.jpg', '.jpeg'):
        image.save(output, format='JPEG', quality=85, optimize=True)
    else:
        image.save(output, format='PNG')
    return base64.b64encode(output.getvalue()).decode('ascii'), image


def build_messages(history, pending):
    # Three recent turns fit the existing small context. Retain just the newest image.
    messages = [dict(m) for m in history[-4:]] + [dict(pending)]
    newest_image = next((i for i in range(len(messages)-1, -1, -1)
                         if messages[i].get('images')), None)
    for i, message in enumerate(messages):
        if i != newest_image:
            message.pop('images', None)
    return [{'role': 'system', 'content': '請使用繁體中文回答，除非使用者指定其他語言。回答清楚簡潔。'}] + messages


class StreamRequest:
    """Use cancellable async I/O inside the worker; Tk stays on its own thread."""
    def __init__(self, host=None, model=None, options=None, think=None):
        self.cancelled = threading.Event()
        self.loop = None
        self.task = None
        self.host = host or HOST
        self.model = model or MODEL
        self.options = options or {'num_predict': 384}
        self.think = think

    def cancel(self):
        self.cancelled.set()
        if self.loop and self.task:
            try:
                self.loop.call_soon_threadsafe(self.task.cancel)
            except RuntimeError:
                pass

    def stream(self, messages, emit):
        asyncio.run(self._stream(messages, emit))

    async def _stream(self, messages, emit):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        writer = None
        try:
            if self.cancelled.is_set():
                return
            body_data = {'model': self.model, 'messages': messages,
                                  'stream': True, 'keep_alive': 0,
                                  'options': self.options}
            if self.think is not None:
                body_data['think'] = self.think
            payload = json.dumps(body_data, ensure_ascii=False).encode('utf-8')
            host, port = self.host.rsplit(':', 1)
            async with asyncio.timeout(900):
                reader, writer = await asyncio.open_connection(host, int(port))
                headers = (f'POST /api/chat HTTP/1.1\r\nHost: {self.host}\r\n'
                           f'Content-Type: application/json\r\nContent-Length: {len(payload)}\r\n'
                           'Connection: close\r\n\r\n').encode('ascii')
                writer.write(headers + payload)
                await writer.drain()
                head = (await reader.readuntil(b'\r\n\r\n')).decode('iso-8859-1').split('\r\n')
                status = int(head[0].split(' ')[1])
                fields = dict(line.lower().split(':', 1) for line in head[1:] if ':' in line)
                chunked = 'chunked' in fields.get('transfer-encoding', '')
                length = int(fields['content-length']) if 'content-length' in fields else None

                async def body():
                    remaining = length
                    while remaining is None or remaining > 0:
                        if chunked:
                            size = int((await reader.readline()).split(b';')[0].strip(), 16)
                            if not size:
                                return
                            data = await reader.readexactly(size)
                            if await reader.readexactly(2) != b'\r\n':
                                raise RuntimeError('無效的串流回應。')
                        else:
                            data = await reader.read(min(65536, remaining) if remaining is not None else 65536)
                            if not data:
                                return
                            if remaining is not None:
                                remaining -= len(data)
                        yield data

                if status != 200:
                    error = bytearray()
                    async for data in body():
                        error.extend(data)
                        if len(error) > 65536:
                            break
                    detail = error.decode('utf-8', errors='replace')
                    try:
                        detail = json.loads(detail).get('error', detail)
                    except ValueError:
                        pass
                    raise RuntimeError(detail or f'HTTP {status}')

                def consume(line):
                    event = json.loads(line)
                    if event.get('error'):
                        raise RuntimeError(event['error'])
                    text = event.get('message', {}).get('content', '')
                    if text:
                        emit('token', text)
                    if event.get('done'):
                        emit('complete', event.get('done_reason', 'stop'))
                        return True
                    return False

                buffer = b''
                async for data in body():
                    buffer += data
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if line.strip() and consume(line):
                            return
                if buffer.strip() and consume(buffer):
                    return
                raise RuntimeError('連線提早結束，這次回覆可能不完整，請重試。')
        except asyncio.CancelledError:
            if not self.cancelled.is_set():
                raise
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except (OSError, asyncio.CancelledError):
                    pass
            self.loop = None
            self.task = None


class ChatApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Llama Vision · 本機圖文聊天')
        self.root.geometry('1100x790')
        self.root.minsize(920, 680)
        self.root.configure(bg=BG)
        self.events = queue.Queue()
        self.history = []
        self.photos = []
        self.pending_path = None
        self.preview = None
        self.busy = False
        self.ready = False
        self.request = None
        self.answer = ''
        self.last_answer = ''
        self.started = 0
        self.turn = None
        self.closed = False
        self.status = tk.StringVar(value='正在連接本機模型…')
        self.fast = tk.BooleanVar(value=True)
        self._build()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(70, self.poll)
        self.root.after(1000, self.tick)
        threading.Thread(target=self.connect, daemon=True).start()

    def _build(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TButton', font=('Microsoft JhengHei UI', 10), padding=(12, 8))
        style.configure('Send.TButton', foreground='white', background=ACCENT)
        style.map('Send.TButton', background=[('active', '#18503F'), ('disabled', '#9CAEA4')])
        style.configure('TCheckbutton', background=BG, font=('Microsoft JhengHei UI', 9))
        header = tk.Frame(self.root, bg=INK, padx=26, pady=19)
        header.pack(fill='x')
        tk.Label(header, text='Llama Vision', font=('Segoe UI', 23, 'bold'),
                 fg='white', bg=INK).pack(side='left')
        tk.Label(header, text='本機圖文聊天', font=('Microsoft JhengHei UI', 11),
                 fg='#C6D8CD', bg=INK, padx=18).pack(side='left', pady=(8, 0))
        tk.Label(header, text='LOCAL  /  11B', font=('Segoe UI', 10, 'bold'),
                 fg='#C6D8CD', bg=INK).pack(side='right')

        toolbar = tk.Frame(self.root, bg=BG, padx=24, pady=14)
        toolbar.pack(fill='x')
        tk.Label(toolbar, textvariable=self.status, fg=ACCENT, bg=BG,
                 font=('Microsoft JhengHei UI', 10)).pack(side='left')
        self.new_button = ttk.Button(toolbar, text='新對話', command=self.new_chat)
        self.new_button.pack(side='right')
        ttk.Button(toolbar, text='複製回覆', command=self.copy_answer).pack(side='right', padx=8)

        body = tk.Frame(self.root, bg=BG, padx=24)
        body.pack(fill='both', expand=True)
        sidebar = tk.Frame(body, bg=BG, width=244)
        sidebar.pack(side='right', fill='y', padx=(20, 0))
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='給模型看一張圖片', font=('Microsoft JhengHei UI', 12, 'bold'),
                 bg=BG, fg=INK, anchor='w').pack(fill='x', pady=(0, 12))
        preview_frame = tk.Frame(sidebar, bg='#E7EBE4', height=140)
        preview_frame.pack(fill='x')
        preview_frame.pack_propagate(False)
        self.preview_label = tk.Label(preview_frame, text='尚未選擇圖片\n\nJPG · PNG · WEBP · BMP',
                                      bg='#E7EBE4', fg=MUTED, font=('Microsoft JhengHei UI', 10),
                                      width=27, height=13)
        self.preview_label.pack(fill='both', expand=True)
        self.image_name = tk.Label(sidebar, text='圖片在本機處理', wraplength=235,
                                   bg=BG, fg=MUTED, justify='left', anchor='w',
                                   font=('Microsoft JhengHei UI', 9))
        self.image_name.pack(fill='x', pady=10)
        self.attach_button = ttk.Button(sidebar, text='＋ 選擇圖片', command=self.choose_image)
        self.attach_button.pack(fill='x', pady=(0, 6))
        self.remove_button = ttk.Button(sidebar, text='移除圖片', command=self.clear_image, state='disabled')
        self.remove_button.pack(fill='x')
        self.fast_check = ttk.Checkbutton(sidebar, text='快速圖片模式（560 px）', variable=self.fast)
        self.fast_check.pack(anchor='w', pady=(16, 4))

        chat_frame = tk.Frame(body, bg=PAPER, highlightbackground='#DCE2D8', highlightthickness=1)
        chat_frame.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(chat_frame)
        scrollbar.pack(side='right', fill='y')
        self.transcript = tk.Text(chat_frame, wrap='word', state='disabled', bg=PAPER, fg=INK,
                                  relief='flat', padx=22, pady=18, cursor='arrow',
                                  font=('Microsoft JhengHei UI', 11), spacing3=8,
                                  yscrollcommand=scrollbar.set)
        self.transcript.pack(fill='both', expand=True)
        scrollbar.config(command=self.transcript.yview)
        self.transcript.tag_configure('user', foreground=ACCENT, font=('Microsoft JhengHei UI', 10, 'bold'))
        self.transcript.tag_configure('assistant', foreground='#876342', font=('Microsoft JhengHei UI', 10, 'bold'))
        self.transcript.tag_configure('note', foreground=MUTED, font=('Microsoft JhengHei UI', 9))
        self.transcript.tag_configure('error', foreground='#A23F3F')
        self.write('從一句話，或一張圖片開始。\n', 'assistant')
        self.write('直接輸入問題，或先選擇右側的圖片。\n\n', 'note')

        composer = tk.Frame(self.root, bg=BG, padx=24, pady=16)
        composer.pack(side='bottom', fill='x', before=body)
        input_frame = tk.Frame(composer, bg=PAPER, highlightbackground='#CCD6CB', highlightthickness=1)
        input_frame.pack(side='left', fill='both', expand=True, padx=(14, 14))
        self.input = tk.Text(input_frame, height=3, wrap='word', relief='flat', padx=12, pady=10,
                             bg=PAPER, fg=INK, font=('Microsoft JhengHei UI', 11), undo=True)
        self.input.pack(fill='both', expand=True)
        self.input.bind('<Control-Return>', self.keyboard_send)
        buttons = tk.Frame(composer, bg=BG)
        buttons.pack(side='right', before=input_frame)
        self.send_button = ttk.Button(buttons, text='傳送 ↗', style='Send.TButton', command=self.send, state='disabled')
        self.send_button.pack(fill='x')
        self.stop_button = ttk.Button(buttons, text='停止回覆', command=self.stop, state='disabled')
        self.stop_button.pack(fill='x', pady=(6, 0))
        tk.Label(self.root, text='Ctrl + Enter 傳送   ·   Enter 換行   ·   關閉視窗不保留聊天紀錄',
                 bg=BG, fg=MUTED, font=('Microsoft JhengHei UI', 9)).pack(side='bottom', before=composer, pady=(0, 14))
        self.input.focus_set()

    def write(self, text, tag=None):
        self.transcript.configure(state='normal')
        self.transcript.insert('end', text, tag or ())
        self.transcript.configure(state='disabled')
        self.transcript.see('end')

    def connect(self):
        try:
            ensure_service()
            self.events.put(('ready', None))
        except Exception as error:
            self.events.put(('connection_error', str(error)))

    def choose_image(self):
        filename = filedialog.askopenfilename(title='選擇要辨識的圖片',
            filetypes=[('圖片', '*.png *.jpg *.jpeg *.webp *.bmp'), ('所有檔案', '*.*')])
        if filename:
            self.attach_image(filename)

    def attach_image(self, filename):
        try:
            _, image = prepare_image(filename, fast=True)
            image.thumbnail((236, 132), Image.Resampling.LANCZOS)
            self.preview = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview, text='', width=236, height=132)
            self.pending_path = Path(filename)
            self.image_name.configure(text=self.pending_path.name)
            self.remove_button.configure(state='normal')
        except Exception as error:
            messagebox.showerror('無法開啟圖片', str(error))

    def clear_image(self):
        self.pending_path = None
        self.preview = None
        self.preview_label.configure(image='', text='尚未選擇圖片\n\nJPG · PNG · WEBP · BMP', width=27, height=13)
        self.image_name.configure(text='圖片在本機處理')
        self.remove_button.configure(state='disabled')

    def keyboard_send(self, event=None):
        self.send()
        return 'break'

    def has_attachment(self):
        return bool(self.pending_path)

    def default_prompt(self):
        return '請描述這張圖片。'

    def prepare_turn(self, text):
        return {'role': 'user', 'content': text}

    def write_attachment_note(self):
        pass

    def send(self):
        if self.busy or not self.ready:
            return
        text = self.input.get('1.0', 'end-1c').strip()
        if not text and not self.has_attachment():
            return
        text = text or self.default_prompt()
        turn = self.prepare_turn(text)
        image = None
        if self.pending_path:
            try:
                encoded, image = prepare_image(self.pending_path, self.fast.get())
                turn['images'] = [encoded]
            except Exception as error:
                messagebox.showerror('無法處理圖片', str(error))
                return
        self.write('你\n', 'user')
        self.write(text + '\n')
        self.write_attachment_note()
        if image:
            image.thumbnail((250, 170), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            self.photos.append(photo)
            self.transcript.configure(state='normal')
            self.transcript.image_create('end', image=photo)
            self.transcript.configure(state='disabled')
            self.write('\n' + self.pending_path.name + '\n', 'note')
        self.write('\n' + self.assistant_name(turn) + '\n', 'assistant')
        self.input.delete('1.0', 'end')
        self.clear_image()
        self.answer = ''
        self.turn = turn
        messages = build_messages(self.history, turn)
        self.request = self.create_request(messages)
        self.started = time.monotonic()
        self.set_busy(True)
        self.status.set('正在載入／思考…')
        threading.Thread(target=self.generate, args=(self.request, messages), daemon=True).start()

    def create_request(self, messages):
        return StreamRequest()

    def assistant_name(self, turn):
        return 'Llama Vision'

    def generate(self, request, messages):
        try:
            request.stream(messages, lambda kind, value: self.events.put((kind, value)))
        except Exception as error:
            if not request.cancelled.is_set():
                self.events.put(('error', str(error)))
        finally:
            self.events.put(('finished', request.cancelled.is_set()))

    def set_busy(self, busy):
        self.busy = busy
        self.send_button.configure(state='disabled' if busy or not self.ready else 'normal')
        self.stop_button.configure(state='normal' if busy else 'disabled')
        self.new_button.configure(state='disabled' if busy else 'normal')
        self.attach_button.configure(state='disabled' if busy else 'normal')
        self.fast_check.configure(state='disabled' if busy else 'normal')

    def stop(self):
        if self.request and self.busy:
            self.request.cancel()
            self.status.set('正在停止…')
            self.stop_button.configure(state='disabled')

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'ready':
                    self.ready = True
                    self.status.set('● 已連線 · CPU 模式')
                    self.set_busy(False)
                elif kind == 'connection_error':
                    self.status.set('連線失敗，請重新開啟程式')
                    self.write('\n無法連接模型：' + value + '\n', 'error')
                elif kind == 'token':
                    self.answer += value
                    self.write(value)
                elif kind == 'complete':
                    self.history.extend([self.turn, {'role': 'assistant', 'content': self.answer}])
                    self.history = self.history[-6:]
                    self.last_answer = self.answer
                    if value == 'length':
                        self.write('\n（本次回覆已達長度上限，可輸入「請繼續」。）', 'note')
                elif kind == 'error':
                    self.write('\n回覆失敗：' + value + '\n可重新輸入問題再試一次。', 'error')
                elif kind == 'finished':
                    if value:
                        self.write('\n（已停止，這次回覆不加入後續對話。）', 'note')
                    self.write('\n\n')
                    elapsed = int(time.monotonic() - self.started)
                    self.status.set(f'● 已連線 · 本次 {elapsed} 秒' + (' · 已停止' if value else ''))
                    self.set_busy(False)
                    self.request = None
                    self.input.focus_set()
        except queue.Empty:
            pass
        self.root.after(70, self.poll)

    def tick(self):
        if self.closed:
            return
        if self.busy and self.request and not self.request.cancelled.is_set():
            seconds = int(time.monotonic() - self.started)
            phase = '正在回覆' if self.answer else '正在載入／思考'
            self.status.set(f'{phase} · {seconds // 60:02d}:{seconds % 60:02d} · CPU 模式')
        self.root.after(1000, self.tick)

    def new_chat(self):
        if self.busy:
            return
        self.history.clear()
        self.photos.clear()
        self.last_answer = ''
        self.clear_image()
        self.transcript.configure(state='normal')
        self.transcript.delete('1.0', 'end')
        self.transcript.configure(state='disabled')
        self.write('新的對話\n\n', 'note')
        self.input.focus_set()

    def copy_answer(self):
        if self.last_answer:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.last_answer)
            if not self.busy:
                self.status.set('已複製上一則完整回覆')

    def close(self):
        self.closed = True
        if self.request:
            self.request.cancel()
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()


if __name__ == '__main__':
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    app = ChatApp(root)
    root.mainloop()
