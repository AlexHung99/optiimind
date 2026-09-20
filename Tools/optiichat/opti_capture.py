"""User-controlled region capture; the full desktop snapshot stays in memory."""
import ctypes
from ctypes import wintypes
import tkinter as tk

from PIL import Image, ImageGrab, ImageTk


def crop_bounds(start, end, view_size, image_size):
    """Map a drag in either direction from the overlay to original image pixels."""
    vw, vh = view_size
    iw, ih = image_size
    if min(vw, vh, iw, ih) <= 0:
        return None
    x1, x2 = sorted((max(0, min(vw, start[0])), max(0, min(vw, end[0]))))
    y1, y2 = sorted((max(0, min(vh, start[1])), max(0, min(vh, end[1]))))
    if x2-x1 < 4 or y2-y1 < 4:
        return None
    return (round(x1*iw/vw), round(y1*ih/vh), round(x2*iw/vw), round(y2*ih/vh))


def desktop_bounds():
    user32 = ctypes.windll.user32
    return tuple(user32.GetSystemMetrics(index) for index in (76, 77, 78, 79))


def position_overlay(window, bounds):
    # Tk's negative geometry offsets mean "from right/bottom", not negative monitor coordinates.
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    handle = user32.GetAncestor(window.winfo_id(), 2)
    if not user32.SetWindowPos(handle, wintypes.HWND(-1), *bounds, 0x0040):
        raise ctypes.WinError(ctypes.get_last_error())


class RegionCapture:
    def __init__(self, root, callback, other_windows=()):
        self.root = root
        self.callback = callback
        self.other_windows = other_windows
        self.hidden = []
        self.overlay = None
        self.snapshot = None
        self.photo = None
        self.origin = None
        self.timer = None
        self.done = False

    def start(self):
        try:
            for window in (self.root, *self.other_windows):
                if window and window.winfo_exists() and window.state() != 'withdrawn':
                    self.hidden.append((window, window.state()))
                    window.withdraw()
            # Allow the compositor to remove our windows before freezing the desktop.
            self.timer = self.root.after(250, self.capture)
        except Exception as error:
            self.finish(error=str(error))

    def capture(self):
        self.timer = None
        if self.done:
            return
        try:
            left, top, width, height = desktop_bounds()
            if width <= 0 or height <= 0:
                raise RuntimeError('無法取得螢幕範圍。')
            self.snapshot = ImageGrab.grab(all_screens=True).convert('RGB')
            self.overlay = tk.Toplevel(self.root)
            self.overlay.withdraw()
            self.overlay.title('OptiiChat · 框選截圖')
            self.overlay.overrideredirect(True)
            self.overlay.attributes('-topmost', True)
            self.overlay.geometry(f'{width}x{height}+0+0')
            self.canvas = tk.Canvas(self.overlay, highlightthickness=0, borderwidth=0, cursor='crosshair')
            self.canvas.pack(fill='both', expand=True)
            self.overlay.deiconify()
            self.overlay.update_idletasks()
            position_overlay(self.overlay, (left, top, width, height))
            # Process the native map/configure events before measuring the canvas.
            self.overlay.update()
            if self.done:
                return
            self.view_size = (self.canvas.winfo_width(), self.canvas.winfo_height())
            if min(self.view_size) <= 1:
                raise RuntimeError('截圖選取視窗無法展開，請重試。')
            display = self.snapshot.resize(self.view_size, Image.Resampling.LANCZOS)
            self.photo = ImageTk.PhotoImage(display)
            self.canvas.create_image(0, 0, image=self.photo, anchor='nw')
            # Stipple darkens only the preview. The saved crop comes from the original snapshot.
            self.shade = self.canvas.create_rectangle(0, 0, *self.view_size, fill='black', stipple='gray25', outline='')
            self.selection = self.canvas.create_rectangle(0, 0, 0, 0, outline='#0ABAB5', width=3)
            px = min(max(self.root.winfo_pointerx()-left, 12), max(12, self.view_size[0]-460))
            py = min(max(self.root.winfo_pointery()-top+24, 12), max(12, self.view_size[1]-60))
            self.canvas.create_rectangle(px, py, px+445, py+40, fill='#14161A', outline='', tags='hint')
            self.canvas.create_text(px+14, py+20, anchor='w', fill='white',
                                    text='拖曳框選範圍 · 放開附加 · Esc／右鍵取消',
                                    font=('Microsoft JhengHei UI', 11), tags='hint')
            self.canvas.bind('<ButtonPress-1>', self.press)
            self.canvas.bind('<B1-Motion>', self.drag)
            self.canvas.bind('<ButtonRelease-1>', self.release)
            self.overlay.bind('<Escape>', lambda _: self.cancel())
            self.overlay.bind('<Button-3>', lambda _: self.cancel())
            self.overlay.protocol('WM_DELETE_WINDOW', self.cancel)
            self.overlay.grab_set()
            self.overlay.focus_force()
        except Exception as error:
            self.finish(error=str(error))

    def point(self, event):
        return (max(0, min(self.view_size[0], event.x)), max(0, min(self.view_size[1], event.y)))

    def press(self, event):
        self.origin = self.point(event)
        self.canvas.delete('hint')
        self.canvas.coords(self.selection, *self.origin, *self.origin)

    def drag(self, event):
        if self.origin:
            self.canvas.coords(self.selection, *self.origin, *self.point(event))

    def release(self, event):
        if self.origin is None:
            return
        bounds = crop_bounds(self.origin, self.point(event), self.view_size, self.snapshot.size)
        self.origin = None
        if bounds:
            self.finish(self.snapshot.crop(bounds))

    def cancel(self):
        self.finish()

    def finish(self, image=None, error=None):
        if self.done:
            return
        self.done = True
        if self.timer:
            self.root.after_cancel(self.timer)
            self.timer = None
        if self.overlay:
            self.overlay.grab_release()
            self.overlay.destroy()
            self.overlay = None
        self.snapshot = None
        self.photo = None
        for window, state in self.hidden:
            if window.winfo_exists():
                window.deiconify()
                window.state(state)
        self.hidden.clear()
        self.callback(image, error)
