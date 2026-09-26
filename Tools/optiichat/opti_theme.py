"""Shared OptiChat colors and window helpers for secondary UI."""
import ctypes
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
import winreg


LIGHT = dict(bg='#EAF3F5', rail='#DFEBEF', panel='#F7FBFD', chat='#FFFFFF',
             user_card='#E3F8FA', assistant_card='#F3F8FA', input='#FFFFFF', selected='#C6F1F3',
             paper='#FFFFFF', ink='#142A38', muted='#647D8E', line='#B8D1D9', accent='#087E88', gold='#986200')
DARK = dict(bg='#091720', rail='#0A1925', panel='#102330', chat='#0D1C27',
            user_card='#103344', assistant_card='#172D3A', input='#142B39', selected='#0A3D4B',
            paper='#132735', ink='#EDF4FA', muted='#9DAFBE', line='#29495B', accent='#38E3EE', gold='#F3CA68')


def system_theme():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return 'light' if winreg.QueryValueEx(key, 'AppsUseLightTheme')[0] else 'dark'
    except OSError:
        return 'light'


def palette(theme):
    return DARK if theme == 'dark' else LIGHT


def ui_font_family(root):
    """Choose an installed Traditional Chinese font for dialogs and prompts."""
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


def set_titlebar_theme(window, theme):
    """Use the chosen app theme for a Windows title bar when DWM supports it."""
    try:
        dark = ctypes.c_int(theme == 'dark')
        ctypes.windll.user32.GetParent.argtypes = [ctypes.c_void_p]
        ctypes.windll.user32.GetParent.restype = ctypes.c_void_p
        child = ctypes.c_void_p(window.winfo_id())
        hwnd = ctypes.windll.user32.GetParent(child) or child.value
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 20, ctypes.byref(dark), ctypes.sizeof(dark))
    except (AttributeError, OSError, tk.TclError):
        pass


def center_on_parent(window, parent, width, height):
    parent.update_idletasks()
    window.update_idletasks()
    screen_x, screen_y = window.winfo_vrootx(), window.winfo_vrooty()
    screen_width, screen_height = window.winfo_vrootwidth(), window.winfo_vrootheight()
    width = min(width, screen_width)
    height = min(height, screen_height)
    x = parent.winfo_rootx() + (parent.winfo_width()-width)//2
    y = parent.winfo_rooty() + (parent.winfo_height()-height)//2
    x = max(screen_x, min(x, screen_x+screen_width-width))
    y = max(screen_y, min(y, screen_y+screen_height-height))
    window.geometry(f'{width}x{height}+{x}+{y}')


def configure_secondary_styles(window, theme, font):
    """Style standalone setup and PDF controls without changing main-app styles."""
    p = palette(theme)
    style = ttk.Style(window)
    style.configure('Secondary.TFrame', background=p['panel'])
    style.configure('Secondary.TLabel', background=p['panel'], foreground=p['ink'], font=(font, 10))
    style.configure('SecondaryMuted.TLabel', background=p['panel'], foreground=p['muted'], font=(font, 10))
    style.configure('SecondaryTitle.TLabel', background=p['panel'], foreground=p['ink'], font=(font, 18, 'bold'))
    style.configure('Secondary.TButton', background=p['panel'], foreground=p['ink'],
                    bordercolor=p['line'], padding=(11, 8), font=(font, 10))
    style.map('Secondary.TButton', background=[('active', p['selected'])],
              foreground=[('disabled', p['muted'])])
    style.configure('SecondaryAccent.TButton', background=p['accent'], foreground=p['bg'],
                    bordercolor=p['accent'], padding=(11, 8), font=(font, 10, 'bold'))
    style.map('SecondaryAccent.TButton', background=[('active', p['selected'])],
              foreground=[('active', p['ink']), ('disabled', p['muted'])])
    style.configure('Secondary.TSpinbox', fieldbackground=p['input'], foreground=p['ink'],
                    arrowsize=14, bordercolor=p['line'], insertcolor=p['ink'])
    style.map('Secondary.TSpinbox', foreground=[('disabled', p['muted'])])


class ThemedDialog(tk.Toplevel):
    """Modal notice, confirmation, or text prompt in the main app's palette."""
    def __init__(self, app, title, message, kind='info', parent=None, initial=''):
        parent = parent or app.root
        super().__init__(parent)
        self.result = None if kind == 'prompt' else False
        self.kind = kind
        theme = app.last_theme or app.resolved_theme()
        p = palette(theme)
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=p['bg'])
        body = tk.Frame(self, bg=p['panel'], padx=24, pady=20,
                        highlightthickness=1, highlightbackground=p['line'])
        body.pack(fill='both', expand=True, padx=8, pady=8)
        heading_color = ('#E49A76' if theme == 'dark' else '#A4482B') if kind == 'error' else p['accent']
        tk.Label(body, text=title, bg=p['panel'], fg=heading_color, anchor='w',
                 font=(app.ui_font, 15, 'bold')).pack(fill='x')
        if kind == 'confirm' and len(message) > 400:
            detail_frame = tk.Frame(body, bg=p['panel'])
            detail_frame.pack(fill='both', expand=True, pady=(14, 8))
            detail = tk.Text(detail_frame, bg=p['input'], fg=p['ink'], wrap='word', height=12,
                             relief='flat', bd=0, padx=10, pady=8, font=(app.ui_font, 10))
            detail_bar = ttk.Scrollbar(detail_frame, command=detail.yview)
            detail.configure(yscrollcommand=detail_bar.set)
            detail.insert('1.0', message)
            detail.configure(state='disabled')
            detail.pack(side='left', fill='both', expand=True)
            detail_bar.pack(side='right', fill='y')
        else:
            tk.Label(body, text=message, bg=p['panel'], fg=p['ink'], anchor='w', justify='left',
                     wraplength=490, font=(app.ui_font, 11)).pack(fill='x', pady=(14, 8))
        self.entry = None
        if kind == 'prompt':
            self.entry = tk.Entry(body, bg=p['input'], fg=p['ink'], insertbackground=p['ink'],
                                  selectbackground=p['accent'], selectforeground=p['bg'],
                                  highlightthickness=1, highlightbackground=p['line'],
                                  highlightcolor=p['accent'], relief='flat', font=(app.ui_font, 11))
            self.entry.insert(0, initial)
            self.entry.pack(fill='x', ipady=7, pady=(6, 8))
        actions = tk.Frame(body, bg=p['panel'])
        actions.pack(fill='x', pady=(16, 0))
        if kind in ('confirm', 'prompt'):
            ttk.Button(actions, text='取消', style='Outline.TButton',
                       command=self.cancel).pack(side='right', padx=(8, 0))
        action_text = ('刪除' if title.startswith('刪除') else '確認') if kind == 'confirm' else '儲存' if kind == 'prompt' else '確定'
        ttk.Button(actions, text=action_text, style='Primary.TButton',
                   command=self.accept).pack(side='right')
        self.protocol('WM_DELETE_WINDOW', self.cancel)
        self.bind('<Escape>', lambda _: self.cancel())
        if kind == 'prompt':
            self.entry.bind('<Return>', lambda _: self.accept())
            self.entry.focus_set()
            self.entry.selection_range(0, 'end')
        else:
            actions.winfo_children()[-1].focus_set()
        self.update_idletasks()
        width = 560
        height = min(440, max(175, body.winfo_reqheight()+16))
        center_on_parent(self, parent, width, height)
        set_titlebar_theme(self, theme)

    def accept(self):
        self.result = self.entry.get() if self.entry is not None else True
        self.destroy()

    def cancel(self):
        self.destroy()

    def show(self):
        self.wait_visibility()
        self.grab_set()
        self.wait_window()
        return self.result
