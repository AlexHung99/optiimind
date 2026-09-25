"""OptiChat conversation layout and presentation widgets."""
from datetime import datetime
import math
import os
import re
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk
from opti_history import attachment_path, preview_path


def _button(parent, text, command, style='Outline.TButton', **options):
    return ttk.Button(parent, text=text, command=command, style=style, **options)


def toolbar_icon(kind, color):
    """Draw crisp, font-independent toolbar icons for both Windows themes."""
    scale = 4
    image = Image.new('RGBA', (24*scale, 24*scale))
    draw = ImageDraw.Draw(image)
    if kind == 'search':
        draw.ellipse((3*scale, 3*scale, 15*scale, 15*scale), outline=color, width=2*scale)
        draw.line((14*scale, 14*scale, 21*scale, 21*scale), fill=color, width=2*scale)
        draw.ellipse((20*scale, 20*scale, 22*scale, 22*scale), fill=color)
    elif kind == 'about':
        draw.ellipse((3*scale, 3*scale, 21*scale, 21*scale), outline=color, width=2*scale)
        draw.rounded_rectangle((11*scale, 6*scale, 13*scale, 14*scale), radius=scale, fill=color)
        draw.ellipse((11*scale, 17*scale, 13*scale, 19*scale), fill=color)
    elif kind == 'settings':
        center = 12*scale
        points = []
        for tooth in range(8):
            for offset, radius in ((-0.43, 8), (-0.27, 11), (0.27, 11), (0.43, 8)):
                angle = 2*math.pi*(tooth+offset)/8-math.pi/2
                points.append((center+radius*scale*math.cos(angle),
                               center+radius*scale*math.sin(angle)))
        draw.polygon(points, fill=color)
        draw.ellipse((center-3*scale, center-3*scale, center+3*scale, center+3*scale),
                     fill=(0, 0, 0, 0))
    return image.resize((24, 24), Image.Resampling.LANCZOS)


def refresh_toolbar_icons(app, theme):
    from opti_app import DARK, LIGHT
    palette = DARK if theme == 'dark' else LIGHT
    app.toolbar_icons = {kind: ImageTk.PhotoImage(toolbar_icon(kind, palette['accent']), master=app.root)
                         for kind in ('settings', 'search', 'about')}
    app.settings_button.configure(image=app.toolbar_icons['settings'])
    app.about_button.configure(image=app.toolbar_icons['about'])
    app.search_button.configure(image=app.toolbar_icons['search'])


def build_ui(app):
    app.route = tk.StringVar(value='自動分流')
    app.metrics = tk.StringVar(value='CPU —  RAM —  GPU —  VRAM —')
    app.audio_status = tk.StringVar(value='語音待命')
    app.search_var = tk.StringVar(value='')
    ttk.Style(app.root).theme_use('clam')

    # Full-width brand bar, history, and the main workspace.
    brandbar = app.frame(app.root, role='panel', height=54, padx=20)
    brandbar.pack(fill='x')
    brandbar.pack_propagate(False)
    app.logo = app.label(brandbar, role='panel')
    app.logo.pack(side='left', padx=(0, 10))
    brand = app.label(brandbar, 'Optiimind', role='panel')
    brand.configure(font=('Georgia', 19, 'bold'))
    brand.pack(side='left')
    app.label(brandbar, 'OptiChat · 本機 AI', role='panel', color='muted').pack(side='left', padx=22)
    app.settings_button = ttk.Button(brandbar, command=app.open_settings, style='Icon.TButton')
    app.settings_button.pack(side='right', pady=7)
    app.about_button = ttk.Button(brandbar, command=app.open_about, style='Icon.TButton')
    app.about_button.pack(side='right', padx=(0, 10), pady=7)

    bottom = app.frame(app.root, role='panel', height=58, padx=26)
    bottom.pack(side='bottom', fill='x')
    bottom.pack_propagate(False)
    metric = app.label(bottom, textvariable=app.metrics, role='panel', color='ink')
    metric.configure(font=('Segoe UI', 10))
    metric.pack(side='left', pady=16)
    app.label(bottom, 'Ctrl+Enter 傳送', role='panel', color='muted').pack(side='right', pady=16)
    app.speech_controls = app.frame(bottom, role='panel')
    app.speak_button = _button(app.speech_controls, '朗讀', app.speak)
    app.speak_button.pack(side='right', padx=18, pady=9)
    _button(app.speech_controls, '匯出 WAV', app.export_audio).pack(side='right', pady=9)
    _button(app.speech_controls, '停止語音', app.stop_speech).pack(side='right', padx=5, pady=9)

    shell = app.frame(app.root, role='bg')
    shell.pack(fill='both', expand=True)

    history = app.frame(shell, role='panel', width=248, padx=14, pady=18,
                        highlightthickness=1)
    history.pack(side='left', fill='y', padx=(12, 12), pady=(12, 12))
    history.pack_propagate(False)
    heading = app.frame(history, role='panel')
    heading.pack(fill='x')
    title = app.label(heading, '對話紀錄', role='panel')
    title.configure(font=(app.ui_font, 14, 'bold'))
    title.pack(side='left')
    app.search_button = ttk.Button(heading, command=lambda: toggle_search(app), style='Icon.TButton')
    app.search_button.pack(side='right')
    app.new_button = _button(history, '+  新對話', app.new_chat, 'Primary.TButton')
    app.new_button.pack(fill='x', pady=(17, 8))
    app.search_entry = ttk.Entry(history, textvariable=app.search_var)
    app.root.bind('<Control-f>', lambda event: toggle_search(app), add=True)
    app.search_var.trace_add('write', lambda *_: build_history_cards(app))
    app.conversation_list = tk.Listbox(history, exportselection=False)
    app.history_context_menu = tk.Menu(history, tearoff=False)
    app.conversation_list.bind('<F2>', app.rename_conversation)
    app.root.bind('<F2>', app.rename_conversation, add=True)
    history_scroll = ttk.Scrollbar(history)
    app.history_canvas = tk.Canvas(history, highlightthickness=0, bd=0,
                                   yscrollcommand=history_scroll.set)
    app.roles.append((app.history_canvas, 'panel', None))
    history_scroll.pack(side='right', fill='y')
    app.history_canvas.pack(fill='both', expand=True)
    history_scroll.configure(command=app.history_canvas.yview)
    app.history_items = app.frame(app.history_canvas, role='panel')
    history_window = app.history_canvas.create_window((0, 0), window=app.history_items, anchor='nw')
    app.history_items.bind('<Configure>', lambda _:
        app.history_canvas.configure(scrollregion=app.history_canvas.bbox('all')))
    app.history_canvas.bind('<Configure>', lambda event:
        app.history_canvas.itemconfigure(history_window, width=event.width))
    center = app.frame(shell, role='bg')
    center.pack(side='left', fill='both', expand=True, padx=(0, 12), pady=(12, 12))
    toolbar = app.frame(center, role='panel', height=64, padx=16, highlightthickness=1)
    toolbar.pack(fill='x')
    toolbar.grid_columnconfigure(0, weight=1)
    toolbar.grid_rowconfigure(0, minsize=64)
    status_label = app.label(toolbar, textvariable=app.status, role='panel', color='accent',
                             anchor='w', justify='left', wraplength=1000)
    status_label.grid(row=0, column=0, sticky='ew', pady=12)
    app.status_banner = toolbar
    app.status_label = status_label

    def fit_status(event):
        width = max(160, event.width - 40)
        if int(status_label.cget('wraplength')) != width:
            status_label.configure(wraplength=width)

    toolbar.bind('<Configure>', fit_status)
    app.root.bind('<Control-Shift-S>', app.take_screenshot)

    app.composer = app.frame(center, role='bg', height=128)
    app.composer.pack(side='bottom', fill='x', pady=(10, 0))
    app.composer.pack_propagate(False)
    actions = app.frame(app.composer, role='bg', width=190)
    actions.pack(side='right', fill='y', padx=(10, 0))
    actions.pack_propagate(False)
    app.send_button = _button(actions, '傳送', app.send, 'Primary.TButton')
    app.send_button.configure(state='disabled')
    app.send_button.pack(fill='x', pady=(0, 7))
    app.stop_button = _button(actions, '停止初始化', app.stop)
    app.stop_button.pack(fill='x')
    input_shell = app.frame(app.composer, role='input', highlightthickness=1, padx=10, pady=9)
    input_shell.pack(fill='both', expand=True)
    controls = app.frame(input_shell, role='input')
    controls.pack(side='bottom', fill='x')
    app.attach_button = _button(controls, '+', app.choose_file, width=3)
    app.attach_button.pack(side='left', anchor='s', padx=(0, 7))
    app.capture_button = _button(controls, '截圖', app.take_screenshot, width=5)
    app.capture_button.pack(side='left', anchor='s', padx=(0, 8))
    input_body = app.frame(input_shell, role='input')
    app.input_body = input_body
    input_body.pack(fill='both', expand=True)
    app.input = tk.Text(input_body, height=3, wrap='word', relief='flat', bd=0, padx=8, pady=5,
                        font=(app.ui_font, 11), undo=True)
    app.roles.append((app.input, 'input', 'ink'))
    app.input.pack(fill='both', expand=True)
    app.input.bind('<Control-Return>', app.keyboard_send)
    app.placeholder = app.label(input_body, '輸入訊息…（可貼上文字、圖片或拖曳檔案）',
                                role='input', color='muted')
    app.placeholder.place(x=18, y=9)
    app.placeholder.bind('<Button-1>', lambda _: app.input.focus_set())
    app.input.bind('<<Modified>>', lambda _: update_placeholder(app), add=True)
    app.input.edit_modified(False)
    chip = app.frame(input_shell, role='input', height=24)
    app.attachment_row = chip
    app.preview_image = app.label(chip, '', role='input', color='muted')
    app.preview_label = app.label(chip, '', role='input', color='muted', anchor='w')
    app.preview_label.pack(side='left', fill='x', expand=True)
    app.image_name = app.preview_label
    app.remove_button = _button(chip, '×', app.clear_image, width=3)
    app.remove_button.configure(state='disabled')
    app.remove_button.pack(side='right')
    app.page_button = _button(chip, '選頁', app.open_pdf_page)
    app.page_button.configure(state='disabled')
    app.pdf_button = app.attach_button
    app.fast_check = ttk.Checkbutton(chip, variable=app.fast)

    # The base chat controller retains the source transcript for persistence and
    # tests. The scrollable cards below are the user-visible conversation.
    app.transcript = tk.Text(center, wrap='word', state='disabled')
    app.visual_surface = app.frame(center, role='chat', highlightthickness=1)
    app.visual_surface.pack(fill='both', expand=True, pady=(12, 0))
    chat_scroll = ttk.Scrollbar(app.visual_surface)
    chat_scroll.pack(side='right', fill='y')
    app.visual_canvas = tk.Canvas(app.visual_surface, bd=0, highlightthickness=0,
                                  yscrollcommand=chat_scroll.set)
    app.roles.append((app.visual_canvas, 'chat', None))
    app.visual_canvas.pack(fill='both', expand=True)
    chat_scroll.configure(command=app.visual_canvas.yview)
    app.visual_body = app.frame(app.visual_canvas, role='chat', padx=18, pady=15)
    chat_window = app.visual_canvas.create_window((0, 0), window=app.visual_body, anchor='nw')
    app.visual_body.bind('<Configure>', lambda _:
        app.visual_canvas.configure(scrollregion=app.visual_canvas.bbox('all')))
    app.visual_canvas.bind('<Configure>', lambda event:
        app.visual_canvas.itemconfigure(chat_window, width=event.width))
    app.root.bind('<MouseWheel>', lambda event: wheel(app, event), add=True)
    app.visual_answer_var = None
    app.write('從一句話開始，或按 + 加入圖片、PDF。\n\n', 'note')
    app.refresh_conversations()
    app.configure_drop()
    render_turns(app)
    app.input.focus_set()


def update_placeholder(app):
    app.input.edit_modified(False)
    if app.input.get('1.0', 'end-1c'):
        app.placeholder.place_forget()
    else:
        app.placeholder.place(x=18, y=9)


def toggle_search(app):
    if app.search_entry.winfo_manager():
        app.search_var.set('')
        app.search_entry.pack_forget()
    else:
        app.search_entry.pack(fill='x', pady=(8, 8), before=app.history_canvas)
        app.search_entry.focus_set()


def show_attachment(app, pdf=False):
    app.attachment_row.pack(side='bottom', fill='x', before=app.input_body)
    if app.pending_path and app.preview:
        app.preview_image.pack(side='left', before=app.preview_label, padx=(0, 9))
        app.composer.configure(height=208)
    else:
        app.preview_image.pack_forget()
        app.composer.configure(height=128)
    if pdf:
        app.page_button.pack(side='right', padx=5, before=app.remove_button)
    else:
        app.page_button.pack_forget()


def hide_attachment(app):
    app.preview_image.pack_forget()
    app.attachment_row.pack_forget()
    app.composer.configure(height=128)


def wheel(app, event):
    canvas = app.history_canvas if str(event.widget).startswith(str(app.history_canvas)) else app.visual_canvas
    canvas.yview_scroll(-int(event.delta/120), 'units')


def search_match(record, query):
    """Find the first visible message containing query, in conversation order."""
    query = query.casefold().strip()
    if not query:
        return None
    turns = record.get('display_turns') or legacy_display_turns(record)
    for index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        for field in ('question', 'attachment', 'answer'):
            value = turn.get(field, '')
            if not isinstance(value, str):
                continue
            visible = ' '.join(value.split())
            position = visible.casefold().find(query)
            if position >= 0:
                start = max(0, position - 24)
                end = min(len(visible), position + len(query) + 48)
                preview = ('…' if start else '') + visible[start:end] + ('…' if end < len(visible) else '')
                return {'turn': index, 'field': field, 'preview': preview}
    transcript = record.get('transcript', '')
    if isinstance(transcript, str):
        visible = ' '.join(transcript.split())
        position = visible.casefold().find(query)
        if position >= 0:
            start = max(0, position - 24)
            end = min(len(visible), position + len(query) + 48)
            preview = ('…' if start else '') + visible[start:end] + ('…' if end < len(visible) else '')
            return {'turn': None, 'field': 'transcript', 'preview': preview}
    title = record.get('title', '')
    if isinstance(title, str) and query in title.casefold():
        return {'turn': None, 'field': 'title', 'preview': ''}
    return None


def search_preview(record, query):
    """Return a short match from visible chat content, or None when absent."""
    if not query:
        return ''
    match = search_match(record, query)
    return None if match is None else match['preview']


def clear_search_highlight(app):
    for turn in getattr(app, 'visual_turn_widgets', ()):
        for widget in turn.values():
            if widget and widget.winfo_exists():
                widget.tag_remove('search_match', '1.0', 'end')


def build_history_cards(app):
    if not hasattr(app, 'history_items'):
        return
    clear_search_highlight(app)
    for child in app.history_items.winfo_children():
        child.destroy()
    app.roles = [(widget, bg, fg) for widget, bg, fg in app.roles if widget.winfo_exists()]
    query = app.search_var.get().casefold().strip()
    selected = app.conversation['id'] if app.conversation else None
    matches = 0
    for index, record in enumerate(app.conversation_index):
        preview = search_preview(record, query)
        if preview is None:
            continue
        matches += 1
        active = record['id'] == selected
        role = 'selected' if active else 'panel'
        card = app.frame(app.history_items, role=role, padx=7, pady=8, highlightthickness=1 if active else 0)
        card.pack(fill='x', pady=2)
        row = app.frame(card, role=role)
        row.pack(fill='x')
        name = record.get('title', '未命名對話')
        shown = name if len(name) <= 40 else name[:39]+'…'
        btn = tk.Button(row, text=shown, anchor='w', relief='flat', bd=0, padx=2,
                        font=(app.ui_font, 10), justify='left', wraplength=174,
                        command=lambda i=index: choose_history(app, i))
        app.roles.append((btn, role, 'ink'))
        btn.pack(side='left', fill='x', expand=True)
        for widget in (card, row, btn):
            widget.bind('<Button-3>', lambda event, i=index: show_history_menu(app, i, event))
        for widget in (card, row):
            widget.bind('<Button-1>', lambda event, i=index: choose_history(app, i))
        created = record.get('created', '')[:16].replace('T', ' ')
        if created and name != created:
            stamp = app.label(card, created, role=role, color='muted')
            stamp.configure(font=(app.ui_font, 9))
            stamp.pack(anchor='w', padx=2)
            stamp.bind('<Button-3>', lambda event, i=index: show_history_menu(app, i, event))
            stamp.bind('<Button-1>', lambda event, i=index: choose_history(app, i))
        if preview:
            excerpt = app.label(card, preview, role=role, color='muted',
                                wraplength=190, justify='left', anchor='w')
            excerpt.pack(fill='x', padx=2, pady=(4, 0))
            excerpt.bind('<Button-3>', lambda event, i=index: show_history_menu(app, i, event))
            excerpt.bind('<Button-1>', lambda event, i=index: choose_history(app, i))
    if query and not matches:
        app.label(app.history_items, '沒有符合的對話', role='panel', color='muted').pack(anchor='w', pady=12)
    if app.last_theme:
        paint_roles(app, app.last_theme)


def legacy_display_turns(record):
    """Show pre-card conversations as separate messages without exposing PDF prompt text."""
    turns = []
    pending = None
    stamp = record.get('created', '')[:16].replace('T', ' ')
    for message in record.get('messages', []):
        if not isinstance(message, dict) or not isinstance(message.get('content'), str):
            continue
        content = message['content']
        if message.get('role') == 'user':
            lines = content.splitlines()
            question = next((line.strip() for line in lines if line.strip()), '')
            attachment = next((line.strip() for line in lines if line.startswith('PDF：')), '')
            pending = {'time': stamp, 'question': (question or record.get('title', '舊版對話'))[:320],
                       'attachment': attachment[:180], 'model': '本機模型', 'answer': ''}
        elif message.get('role') == 'assistant' and pending:
            pending['answer'] = content or '（舊版對話沒有保存完整回覆）'
            turns.append(pending)
            pending = None
    if pending:
        pending['answer'] = '（舊版對話沒有保存完整回覆）'
        turns.append(pending)
    return turns


def choose_history(app, index):
    identifier = app.conversation_index[index]['id']
    app.conversation_list.selection_clear(0, 'end')
    app.conversation_list.selection_set(index)
    app.select_conversation()
    if app.conversation and app.conversation['id'] == identifier:
        scroll_to_search_match(app)


def scroll_to_search_match(app):
    query = app.search_var.get().strip()
    if not query or not app.conversation:
        return
    match = search_match(app.conversation, query)
    if not match:
        return
    clear_search_highlight(app)
    app.visual_body.update_idletasks()
    turn = match['turn']
    if turn is None or turn >= len(app.visual_turn_widgets):
        app.visual_canvas.yview_moveto(0.0)
        return
    widget = app.visual_turn_widgets[turn].get(match['field'])
    if not widget or not widget.winfo_exists():
        app.visual_canvas.yview_moveto(0.0)
        return
    position = widget.search(query, '1.0', nocase=True, stopindex='end')
    offset = 0
    if position:
        widget.tag_add('search_match', position, f'{position}+{len(query)}c')
        widget.tag_configure('search_match', background='#F3CA68', foreground='#142A38')
        line = widget.dlineinfo(position)
        if line:
            offset = line[1]
    y = widget.winfo_rooty() - app.visual_body.winfo_rooty() + offset
    app.visual_canvas.yview_moveto(max(0, y - 32) / max(1, app.visual_body.winfo_height()))


def rename_history(app, index):
    app.conversation_list.selection_clear(0, 'end')
    app.conversation_list.selection_set(index)
    app.rename_conversation()


def show_history_menu(app, index, event):
    menu = app.history_context_menu
    menu.delete(0, 'end')
    menu.add_command(label='重新命名', command=lambda: rename_history(app, index))
    menu.add_command(label='刪除對話',
                     command=lambda: app.delete_conversation(app.conversation_index[index]['id']))
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
    return 'break'


def render_turns(app):
    for child in app.visual_body.winfo_children():
        child.destroy()
    app.roles = [(widget, bg, fg) for widget, bg, fg in app.roles if widget.winfo_exists()]
    app.visual_answer_var = None
    app.visual_photos = []
    app.visual_turn_widgets = []
    record = app.conversation or {}
    turns = record.get('display_turns') or legacy_display_turns(record)
    if not turns:
        previous = (app.conversation or {}).get('transcript', '').strip()
        text = previous if previous else '從一句話開始，或按 + 加入圖片、PDF。'
        welcome = app.label(app.visual_body, text, role='chat', color='muted',
                            justify='left', wraplength=680)
        welcome.configure(font=(app.ui_font, 12))
        welcome.pack(anchor='w', padx=28, pady=36)
    else:
        for index, turn in enumerate(turns):
            add_turn(app, turn, index, scroll=False)
    if app.last_theme:
        paint_roles(app, app.last_theme)
    settle_chat_scroll(app, to_bottom=bool(turns))


def settle_chat_scroll(app, to_bottom=True):
    # The canvas still has the previous conversation's scroll range until Tk
    # finishes laying out the replacement cards.
    app.visual_body.update_idletasks()
    app.visual_canvas.configure(scrollregion=app.visual_canvas.bbox('all'))
    app.visual_canvas.yview_moveto(1.0 if to_bottom else 0.0)


def add_turn(app, turn, index, scroll=True):
    row = app.frame(app.visual_body, role='chat')
    row.pack(fill='x', pady=(6, 20))
    stamp = turn.get('time') or datetime.now().strftime('%Y-%m-%d %H:%M')
    user_header = app.label(row, f'{stamp}   你', role='chat', color='muted', anchor='e')
    user_header.pack(anchor='e', padx=(0, 24), pady=(0, 5))
    user = app.frame(row, role='user_card', padx=15, pady=12, highlightthickness=1)
    user.pack(anchor='e', padx=(60, 24))
    user_text = selectable_text(app, user, turn.get('question', ''), 'user_card', max_width=650)
    attachment = turn.get('attachment')
    attachment_text = None
    if attachment:
        attachment_text = add_attachment_card(app, user, turn, index)
    assistant = app.frame(row, role='chat')
    assistant.pack(fill='x', pady=(22, 0))
    header = app.frame(assistant, role='chat')
    header.pack(anchor='w', padx=10, pady=(0, 6))
    model_label = app.label(header, short_model_name(turn.get('model')), role='chat', color='gold')
    model_label.configure(font=(app.ui_font, 10, 'bold'))
    model_label.pack(side='left')
    app.label(header, '    '+stamp, role='chat', color='muted').pack(side='left')
    answer_card = app.frame(assistant, role='assistant_card', padx=20, pady=17, highlightthickness=1)
    answer_card.pack(fill='x', padx=(25, 145))
    if turn.get('answer'):
        answer_text = render_answer(app, answer_card, turn['answer'])
        app.visual_answer_var = None
    else:
        answer_text = selectable_text(app, answer_card, '正在載入／思考…', 'assistant_card')
        app.visual_answer_var = SelectableTextValue(answer_text)
    app.visual_turn_widgets.append({'question': user_text, 'attachment': attachment_text,
                                    'answer': answer_text})
    if scroll:
        if app.last_theme:
            paint_roles(app, app.last_theme)
        settle_chat_scroll(app)


def add_attachment_card(app, user, turn, index):
    attachment = turn['attachment']
    card = app.frame(user, role='user_card', padx=9, pady=8, highlightthickness=1)
    card.pack(anchor='w', pady=(10, 0))
    is_pdf = attachment.startswith('PDF：')
    photo = None
    if not is_pdf and turn.get('preview') and app.conversation:
        try:
            with Image.open(preview_path(app.conversation['id'], index)) as source:
                thumbnail = source.copy()
            thumbnail.thumbnail((160, 108), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(thumbnail, master=app.root)
        except (OSError, ValueError):
            pass
    if photo is not None:
        app.visual_photos.append(photo)
        picture = app.label(card, role='user_card')
        picture.configure(image=photo)
        picture.pack(side='left', padx=(0, 10))
        visual = picture
    else:
        icon = tk.Canvas(card, width=42, height=50, bd=0, highlightthickness=0)
        app.roles.append((icon, 'user_card', None))
        icon.pack(side='left', padx=(0, 10))
        visual = icon
        if is_pdf:
            icon.create_polygon(6, 2, 28, 2, 37, 11, 37, 48, 6, 48,
                                fill='#FFFFFF', outline='#E34C51', width=2)
            icon.create_line(28, 2, 28, 11, 37, 11, fill='#E34C51', width=2)
            icon.create_text(21, 31, text='PDF', fill='#C52832', font=(app.ui_font, 9, 'bold'))
        else:
            icon.create_rectangle(4, 7, 38, 43, outline='#087E88', width=2)
            icon.create_oval(26, 13, 32, 19, fill='#087E88', outline='')
            icon.create_line(8, 37, 18, 26, 24, 32, 30, 24, 35, 31, fill='#087E88', width=2)
    info = selectable_text(app, card, attachment, 'user_card', max_width=460)
    info.pack_configure(side='left', anchor='center')
    gesture = '<Double-Button-1>' if is_pdf else '<Button-1>'
    for widget in (card, visual):
        widget.configure(cursor='hand2')
        widget.bind(gesture, lambda event: open_attachment(app, turn, index))
    info.configure(cursor='hand2')
    if is_pdf:
        info.bind(gesture, lambda event: open_attachment(app, turn, index))
    else:
        # Keep normal drag-selection on the filename; a simple click opens it.
        info.bind('<ButtonRelease-1>', lambda event: info.after_idle(
            lambda: None if info.tag_ranges('sel') else open_attachment(app, turn, index)))
    return info


def open_attachment(app, turn, index):
    """Open only files belonging to the active conversation's validated ID/turn."""
    record = app.conversation or {}
    identifier = record.get('id')
    kind = turn.get('attachment_kind')
    is_pdf = kind == 'pdf' or turn.get('attachment', '').startswith('PDF：')
    try:
        if kind in ('pdf', 'image') and identifier:
            path = attachment_path(identifier, index, kind)
        elif not is_pdf and turn.get('preview') and identifier:
            path = preview_path(identifier, index)
        else:
            messagebox.showinfo('原始附件未保存', '這是舊版對話，沒有保存原始 PDF；請重新附加檔案。', parent=app.root)
            return 'break'
        if not path.is_file():
            messagebox.showwarning('找不到附件', '這份對話的附件檔案已不存在。', parent=app.root)
            return 'break'
        if is_pdf:
            os.startfile(str(path))
        else:
            ImageViewer(app, path, turn.get('attachment', '圖片'))
    except (OSError, ValueError) as error:
        messagebox.showerror('無法開啟附件', str(error), parent=app.root)
    return 'break'


class ImageViewer(tk.Toplevel):
    def __init__(self, app, path, title):
        super().__init__(app.root)
        self.title(title)
        self.transient(app.root)
        self.bind('<Escape>', lambda event: self.destroy())
        from opti_app import DARK, LIGHT
        palette = DARK if app.last_theme == 'dark' else LIGHT
        self.configure(bg=palette['panel'])
        with Image.open(path) as source:
            image = source.convert('RGB')
        image.thumbnail((max(320, self.winfo_screenwidth()-160),
                         max(240, self.winfo_screenheight()-190)), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image, master=self)
        caption = tk.Label(self, text=title, bg=palette['panel'], fg=palette['ink'],
                           font=(app.ui_font, 11), anchor='w', padx=16, pady=12)
        caption.pack(fill='x')
        tk.Label(self, image=self.photo, bg=palette['panel']).pack(padx=16, pady=(0, 16))
        width, height = max(420, image.width+32), image.height+76
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width()-width)//2)
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height()-height)//2)
        x = min(max(0, x), max(0, self.winfo_screenwidth()-width))
        y = min(max(0, y), max(0, self.winfo_screenheight()-height))
        self.geometry(f'{width}x{height}+{x}+{y}')


def short_model_name(value):
    """Show only the model family in reply headings; keep the full saved ID."""
    model = str(value or '').split(' · ', 1)[0].rsplit('/', 1)[-1].split(':', 1)[0]
    for prefix, label in (('mllama', 'Llama'), ('llama', 'Llama'), ('gemma', 'Gemma'),
                          ('qwen', 'Qwen'), ('deepseek', 'DeepSeek'), ('mistral', 'Mistral'),
                          ('phi', 'Phi'), ('gpt', 'GPT'), ('llava', 'LLaVA')):
        if model.lower().startswith(prefix):
            return label
    match = re.match(r'[^\W\d_]+', model, re.UNICODE)
    return match.group().capitalize() if match else '本機模型'


def render_answer(app, parent, content):
    """Keep the whole response selectable while retaining heading emphasis."""
    widget = selectable_text(app, parent, '', 'assistant_card')
    widget.configure(state='normal')
    for index, line in enumerate(content.split('\n')):
        if index:
            widget.insert('end', '\n')
        value = line.strip()
        heading = bool(re.match(r'^(?:#{1,4}\s+|[一二三四五六七八九十]+[、．.])', value))
        numbered = bool(re.match(r'^\d+[.、．]\s*', value))
        widget.insert('end', line, 'heading' if heading else 'numbered' if numbered else ())
    widget.configure(state='disabled')
    fit_text_height(widget)
    return widget


def copy_selected_text(widget):
    try:
        selected = widget.get('sel.first', 'sel.last')
    except tk.TclError:
        return 'break'
    widget.clipboard_clear()
    widget.clipboard_append(selected)
    return 'break'


def select_all_text(widget):
    widget.tag_add('sel', '1.0', 'end-1c')
    widget.focus_set()
    return 'break'


def fit_text_height(widget):
    if not widget.winfo_exists() or widget.winfo_width() <= 1:
        return
    count = widget.count('1.0', 'end', 'displaylines')
    lines = max(1, count[0] if count else 1)
    if int(widget.cget('height')) != lines:
        widget.configure(height=lines)


def selectable_text(app, parent, content, role, max_width=None):
    font = tkfont.Font(root=app.root, family=app.ui_font, size=11)
    if max_width:
        widest = max((font.measure(line) for line in content.split('\n')), default=0)
        width = math.ceil(min(max_width, max(100, widest+12))/max(1, font.measure('0')))
    else:
        width = 1
    widget = tk.Text(parent, width=width, height=1, wrap='word', relief='flat', bd=0,
                     padx=0, pady=0, font=font, cursor='xterm', exportselection=False,
                     highlightthickness=0, takefocus=True)
    widget._opti_font = font
    app.roles.append((widget, role, 'ink'))
    widget.insert('1.0', content)
    widget.configure(state='disabled')
    widget.tag_configure('heading', font=(app.ui_font, 12, 'bold'))
    widget.tag_configure('numbered', foreground=('#38E3EE' if app.last_theme == 'dark' else '#087E88'))
    widget.pack(fill='x', anchor='w')
    widget.bind('<Configure>', lambda event=None: widget.after_idle(lambda: fit_text_height(widget)))
    widget.bind('<MouseWheel>', lambda event: (wheel(app, event), 'break')[1])
    widget.bind('<Control-c>', lambda event: copy_selected_text(widget))
    widget.bind('<Control-a>', lambda event: select_all_text(widget))
    menu = tk.Menu(widget, tearoff=False)
    menu.add_command(label='複製', command=lambda: copy_selected_text(widget))
    menu.add_command(label='全選', command=lambda: select_all_text(widget))
    def show_menu(event):
        menu.entryconfigure(0, state='normal' if widget.tag_ranges('sel') else 'disabled')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'
    widget.bind('<Button-3>', show_menu)
    widget.after_idle(lambda: fit_text_height(widget))
    return widget


class SelectableTextValue:
    def __init__(self, widget):
        self.widget = widget

    def set(self, value):
        if not self.widget.winfo_exists():
            return
        self.widget.configure(state='normal')
        self.widget.delete('1.0', 'end')
        self.widget.insert('1.0', value)
        self.widget.configure(state='disabled')
        self.widget.after_idle(lambda: fit_text_height(self.widget))


def paint_roles(app, theme):
    from opti_app import DARK, LIGHT
    p = DARK if theme == 'dark' else LIGHT
    remaining = []
    for widget, bg, fg in app.roles:
        if not widget.winfo_exists():
            continue
        widget.configure(bg=p[bg])
        if fg:
            widget.configure(fg=p[fg])
        if isinstance(widget, tk.Text):
            widget.configure(insertbackground=p['ink'], selectbackground=p['accent'],
                             selectforeground=p['bg'])
            widget.tag_configure('numbered', foreground=p['accent'])
        if isinstance(widget, tk.Frame) and widget.cget('highlightthickness'):
            widget.configure(highlightbackground=p['accent'] if bg == 'selected' else p['line'])
        remaining.append((widget, bg, fg))
    app.roles = remaining
