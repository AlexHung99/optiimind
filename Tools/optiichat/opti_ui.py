"""OptiChat conversation layout and presentation widgets."""
from datetime import datetime
import re
import tkinter as tk
from tkinter import ttk


def _button(parent, text, command, style='Outline.TButton', **options):
    return ttk.Button(parent, text=text, command=command, style=style, **options)


def build_ui(app):
    app.route = tk.StringVar(value='自動分流')
    app.metrics = tk.StringVar(value='CPU —  RAM —  GPU —  VRAM —')
    app.audio_status = tk.StringVar(value='語音待命')
    app.search_var = tk.StringVar(value='')
    ttk.Style(app.root).theme_use('clam')

    # Full-width brand bar, then an icon rail, history, and the main workspace.
    brandbar = app.frame(app.root, role='panel', height=54, padx=20)
    brandbar.pack(fill='x')
    brandbar.pack_propagate(False)
    app.logo = app.label(brandbar, role='panel')
    app.logo.pack(side='left', padx=(0, 10))
    brand = app.label(brandbar, 'Optiimind', role='panel')
    brand.configure(font=('Georgia', 19, 'bold'))
    brand.pack(side='left')
    app.label(brandbar, 'OptiChat · 本機 AI 工作室', role='panel', color='muted').pack(side='left', padx=22)

    bottom = app.frame(app.root, role='panel', height=58, padx=26)
    bottom.pack(side='bottom', fill='x')
    bottom.pack_propagate(False)
    metric = app.label(bottom, textvariable=app.metrics, role='panel', color='ink')
    metric.configure(font=('Segoe UI', 10))
    metric.pack(side='left', pady=16)
    app.label(bottom, 'Ctrl+Enter 傳送 · × 常駐', role='panel', color='muted').pack(side='right', pady=16)
    app.speak_button = _button(bottom, '朗讀', app.speak)
    app.speak_button.pack(side='right', padx=18, pady=9)
    _button(bottom, '匯出 WAV', app.export_audio).pack(side='right', pady=9)
    _button(bottom, '停止語音', app.stop_speech).pack(side='right', padx=5, pady=9)

    shell = app.frame(app.root, role='bg')
    shell.pack(fill='both', expand=True)
    rail = app.frame(shell, role='rail', width=74, padx=8, pady=18)
    rail.pack(side='left', fill='y')
    rail.pack_propagate(False)
    _button(rail, '對話', app.new_chat, 'Rail.TButton').pack(fill='x', pady=(0, 18))
    _button(rail, '歷史', lambda: app.conversation_list.focus_set(), 'Rail.TButton').pack(fill='x', pady=4)
    _button(rail, '設定', app.open_settings, 'Rail.TButton').pack(fill='x', pady=4)

    history = app.frame(shell, role='panel', width=248, padx=14, pady=18,
                        highlightthickness=1)
    history.pack(side='left', fill='y', padx=(0, 12), pady=(12, 12))
    history.pack_propagate(False)
    heading = app.frame(history, role='panel')
    heading.pack(fill='x')
    title = app.label(heading, '對話紀錄', role='panel')
    title.configure(font=(app.ui_font, 14, 'bold'))
    title.pack(side='left')
    _button(heading, '搜尋', lambda: toggle_search(app)).pack(side='right')
    app.new_button = _button(history, '+  新對話', app.new_chat, 'Primary.TButton')
    app.new_button.pack(fill='x', pady=(17, 8))
    app.search_entry = ttk.Entry(history, textvariable=app.search_var)
    app.search_var.trace_add('write', lambda *_: build_history_cards(app))
    app.conversation_list = tk.Listbox(history, exportselection=False)
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
    _button(history, '重新命名', app.rename_conversation).pack(fill='x', pady=(8, 4))
    _button(history, '重新檢查模型', app.refresh_models).pack(fill='x')

    center = app.frame(shell, role='bg')
    center.pack(side='left', fill='both', expand=True, padx=(0, 12), pady=(12, 12))
    toolbar = app.frame(center, role='panel', height=64, padx=16, highlightthickness=1)
    toolbar.pack(fill='x')
    toolbar.pack_propagate(False)
    app.label(toolbar, textvariable=app.status, role='panel', color='accent',
              wraplength=470, justify='left').pack(side='left', fill='x', expand=True)
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


def build_history_cards(app):
    if not hasattr(app, 'history_items'):
        return
    for child in app.history_items.winfo_children():
        child.destroy()
    app.roles = [(widget, bg, fg) for widget, bg, fg in app.roles if widget.winfo_exists()]
    query = app.search_var.get().casefold().strip()
    selected = app.conversation['id'] if app.conversation else None
    for index, record in enumerate(app.conversation_index):
        if query and query not in record.get('title', '').casefold():
            continue
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
        menu = tk.Button(row, text='...', relief='flat', bd=0, padx=1,
                         command=lambda i=index: rename_history(app, i))
        app.roles.append((menu, role, 'muted'))
        menu.pack(side='right')
        created = record.get('created', '')[:16].replace('T', ' ')
        if created and name != created:
            stamp = app.label(card, created, role=role, color='muted')
            stamp.configure(font=(app.ui_font, 9))
            stamp.pack(anchor='w', padx=2)
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
    app.conversation_list.selection_clear(0, 'end')
    app.conversation_list.selection_set(index)
    app.select_conversation()


def rename_history(app, index):
    app.conversation_list.selection_clear(0, 'end')
    app.conversation_list.selection_set(index)
    app.rename_conversation()


def render_turns(app):
    for child in app.visual_body.winfo_children():
        child.destroy()
    app.roles = [(widget, bg, fg) for widget, bg, fg in app.roles if widget.winfo_exists()]
    app.visual_answer_var = None
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
        for turn in turns:
            add_turn(app, turn, scroll=False)
    if app.last_theme:
        paint_roles(app, app.last_theme)
    settle_chat_scroll(app, to_bottom=bool(turns))


def settle_chat_scroll(app, to_bottom=True):
    # The canvas still has the previous conversation's scroll range until Tk
    # finishes laying out the replacement cards.
    app.visual_body.update_idletasks()
    app.visual_canvas.configure(scrollregion=app.visual_canvas.bbox('all'))
    app.visual_canvas.yview_moveto(1.0 if to_bottom else 0.0)


def add_turn(app, turn, scroll=True):
    row = app.frame(app.visual_body, role='chat')
    row.pack(fill='x', pady=(6, 20))
    stamp = turn.get('time') or datetime.now().strftime('%Y-%m-%d %H:%M')
    user_header = app.label(row, f'{stamp}   你', role='chat', color='muted', anchor='e')
    user_header.pack(anchor='e', padx=(0, 24), pady=(0, 5))
    user = app.frame(row, role='user_card', padx=15, pady=12, highlightthickness=1)
    user.pack(anchor='e', padx=(60, 24))
    question = app.label(user, turn.get('question', ''), role='user_card', color='ink',
                         justify='left', wraplength=650)
    question.configure(font=(app.ui_font, 11))
    question.pack(anchor='w')
    attachment = turn.get('attachment')
    if attachment:
        info = app.label(user, '附件：'+attachment, role='user_card', color='muted',
                         justify='left', wraplength=620)
        info.pack(anchor='w', pady=(10, 0))
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
        render_answer(app, answer_card, turn['answer'])
        app.visual_answer_var = None
    else:
        answer_var = tk.StringVar(value='正在載入／思考…')
        answer = app.label(answer_card, textvariable=answer_var, role='assistant_card', color='ink',
                           justify='left', anchor='w', wraplength=730)
        answer.configure(font=(app.ui_font, 11))
        answer.pack(fill='x')
        app.visual_answer_var = answer_var
    if scroll:
        if app.last_theme:
            paint_roles(app, app.last_theme)
        settle_chat_scroll(app)


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
    """Add lightweight typographic hierarchy without interpreting model HTML."""
    for line in content.splitlines():
        value = line.strip()
        if not value:
            spacer = app.frame(parent, role='assistant_card', height=9)
            spacer.pack(fill='x')
            continue
        heading = bool(re.match(r'^(?:#{1,4}\s+|[一二三四五六七八九十]+[、．.])', value))
        numbered = bool(re.match(r'^\d+[.、．]\s*', value))
        if value.startswith('#'):
            value = value.lstrip('# ').strip()
        label = app.label(parent, value, role='assistant_card',
                          color='accent' if numbered else 'ink', justify='left',
                          anchor='w', wraplength=710)
        label.configure(font=(app.ui_font, 11 if not heading else 12,
                              'bold' if heading else 'normal'))
        label.pack(fill='x', pady=(2, 0))


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
            widget.configure(insertbackground=p['ink'], selectbackground=p['accent'])
        if isinstance(widget, tk.Frame) and widget.cget('highlightthickness'):
            widget.configure(highlightbackground=p['accent'] if bg == 'selected' else p['line'])
        remaining.append((widget, bg, fg))
    app.roles = remaining
