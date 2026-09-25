"""First-launch dependency guidance for the self-contained Windows installer."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from opti_install import COMPAT, install_compat, install_ollama, ollama_installed


def dependencies_ready():
    return ollama_installed() and (COMPAT/'ollama.exe').is_file()


def run_setup():
    root = tk.Tk()
    root.title('OptiChat · 首次使用準備')
    root.geometry('640x340')
    root.resizable(False, False)
    body = ttk.Frame(root, padding=28)
    body.pack(fill='both', expand=True)
    ttk.Label(body, text='歡迎使用 OptiChat', font=('Microsoft JhengHei UI', 19, 'bold')).pack(anchor='w')
    ttk.Label(body, text='Python 與介面套件已包含在安裝包內。\n缺少 Ollama 時會自動下載並安裝；Vision 相容服務另需約 2.1 GB。\n首次使用若缺少 llama3.2-vision，也會自動下載（約 7.8 GB）。',
              wraplength=580, justify='left').pack(anchor='w', pady=18)
    ttk.Button(body, text='開啟 Ollama 官方下載頁',
               command=lambda: webbrowser.open('https://ollama.com/download/windows')).pack(anchor='w')
    status = tk.StringVar(value='正在檢查所需軟體…')
    ttk.Label(body, textvariable=status, wraplength=580).pack(anchor='w', pady=16)
    rows = ttk.Frame(body)
    rows.pack(fill='x')
    events, cancelled = queue.Queue(), threading.Event()
    state = {'busy': False, 'ready': False}

    def close():
        if state['busy']:
            cancelled.set()
            status.set('正在取消，請稍候…')
        else:
            root.destroy()

    def start():
        if state['busy']:
            return
        state['busy'] = True
        cancelled.clear()
        proceed.configure(state='disabled')
        status.set('正在準備所需軟體…')
        def worker():
            try:
                install_ollama(progress=lambda value: events.put(('status', value)), cancelled=cancelled)
                if cancelled.is_set():
                    raise RuntimeError('安裝已取消。')
                install_compat(progress=lambda value: events.put(('status', value)), cancelled=cancelled)
                events.put(('ready', None))
            except Exception as error:
                events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == 'status':
                status.set(value)
            elif kind == 'ready':
                state['busy'] = False
                state['ready'] = not cancelled.is_set()
                root.destroy()
                return
            else:
                state['busy'] = False
                status.set(value)
                proceed.configure(state='normal')
                if cancelled.is_set():
                    root.destroy()
                    return
        root.after(100, poll)

    proceed = ttk.Button(rows, text='重試安裝', command=start)
    proceed.pack(side='right')
    ttk.Button(rows, text='稍後再說', command=close).pack(side='right', padx=10)
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, poll)
    root.after(150, start)
    root.mainloop()
    return state['ready']
