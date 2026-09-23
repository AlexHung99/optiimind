"""First-launch dependency guidance for the self-contained Windows installer."""
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import ttk
import webbrowser

from opti_install import LOCAL, COMPAT, install_compat


def ollama_installed():
    return (LOCAL/'Programs'/'Ollama'/'ollama.exe').is_file() or bool(shutil.which('ollama'))


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
    ttk.Label(body, text='Python 與介面套件已包含在安裝包內。\n請先安裝 Ollama，再按「繼續」。缺少 Vision 相容服務時會下載約 2.1 GB。\n進入聊天後，若沒有模型，會自動下載 llama3.2-vision（約 7.8 GB）。',
              wraplength=580, justify='left').pack(anchor='w', pady=18)
    ttk.Button(body, text='開啟 Ollama 官方下載頁',
               command=lambda: webbrowser.open('https://ollama.com/download/windows')).pack(anchor='w')
    status = tk.StringVar(value='已偵測到 Ollama，可以繼續。' if ollama_installed() else '尚未偵測到 Ollama；安裝完成後請按「繼續」。')
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
        if not ollama_installed():
            status.set('請先完成 Ollama 安裝，再按「繼續」。')
            return
        state['busy'] = True
        cancelled.clear()
        proceed.configure(state='disabled')
        status.set('正在準備相容服務…')
        def worker():
            try:
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

    proceed = ttk.Button(rows, text='繼續', command=start)
    proceed.pack(side='right')
    ttk.Button(rows, text='稍後再說', command=close).pack(side='right', padx=10)
    root.protocol('WM_DELETE_WINDOW', close)
    root.after(100, poll)
    root.mainloop()
    return state['ready']
