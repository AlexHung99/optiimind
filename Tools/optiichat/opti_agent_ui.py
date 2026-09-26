"""Agent tab and task timeline, kept separate from ordinary chat history."""
from copy import deepcopy
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from llama_vision_ui import StreamRequest
from opti_agent import AgentRunner, delete_task, list_tasks, new_task, save_task
from opti_core import ensure_model_service, model_choices, model_service_kind, route_messages
from opti_ui import auto_scrollbar, fit_scroll_region


ACTION_NAMES = {'list_files': '列出檔案', 'read_file': '讀取檔案', 'search_files': '搜尋內容',
                'read_pdf': '讀取 PDF', 'read_excel': '讀取 Excel', 'read_word': '讀取 Word',
                'edit_text': '編輯文字檔', 'edit_excel': '編輯 Excel', 'edit_word': '編輯 Word'}


class AgentWorkspace:
    def __init__(self, app, sidebar, center, chat_sidebar, chat_center):
        self.app = app
        self.sidebar = sidebar
        self.center = center
        self.chat_sidebar = chat_sidebar
        self.chat_center = chat_center
        self.runner = None
        self.request = None
        self.task = new_task()
        self.tasks = []
        self.mode = 'chat'
        self.status = tk.StringVar(app.root, value='選擇資料夾、輸入任務，Agent 可讀取與編輯文書檔案。')
        self.folder = tk.StringVar(app.root, value='')
        self._build_sidebar()
        self._build_center()
        self.refresh_tasks()
        self.render()

    def _build_sidebar(self):
        heading = self.app.label(self.sidebar, 'Agent 任務', role='panel')
        heading.configure(font=(self.app.ui_font, 14, 'bold'))
        heading.pack(anchor='w', pady=(2, 12))
        ttk.Button(self.sidebar, text='+  新任務', command=self.new, style='Primary.TButton').pack(fill='x', pady=(0, 10))
        self.list_canvas = tk.Canvas(self.sidebar, highlightthickness=0, bd=0)
        self.app.roles.append((self.list_canvas, 'panel', None))
        self.list_canvas.pack(fill='both', expand=True)
        bar = ttk.Scrollbar(self.sidebar, command=self.list_canvas.yview)
        auto_scrollbar(self.list_canvas, bar)
        self.list_body = self.app.frame(self.list_canvas, role='panel')
        window = self.list_canvas.create_window((0, 0), window=self.list_body, anchor='nw')
        self.list_body.bind('<Configure>', lambda _: fit_scroll_region(self.list_canvas))
        self.list_canvas.bind('<Configure>', lambda event: (
            self.list_canvas.itemconfigure(window, width=event.width), fit_scroll_region(self.list_canvas)))
        self.menu = tk.Menu(self.sidebar, tearoff=False)

    def _build_center(self):
        header = self.app.frame(self.center, role='panel', padx=19, pady=15, highlightthickness=1)
        header.pack(fill='x')
        title = self.app.label(header, '本機 Agent', role='panel', color='accent')
        title.configure(font=(self.app.ui_font, 15, 'bold'))
        title.pack(anchor='w')
        self.app.label(header, '內建技能：文字檔、Excel、Word 可讀取與編輯；PDF 可讀取文字。編輯前會請你確認，並另存新檔。',
                       role='panel', color='muted', anchor='w').pack(fill='x', pady=(5, 0))

        setup = self.app.frame(self.center, role='panel', padx=16, pady=14, highlightthickness=1)
        setup.pack(fill='x', pady=(12, 0))
        self.app.label(setup, '工作資料夾', role='panel').pack(anchor='w')
        folder_row = self.app.frame(setup, role='panel')
        folder_row.pack(fill='x', pady=(5, 11))
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder, state='readonly')
        self.folder_entry.pack(side='left', fill='x', expand=True)
        self.folder_button = ttk.Button(folder_row, text='選擇資料夾', command=self.choose_folder,
                                        style='Outline.TButton')
        self.folder_button.pack(side='left', padx=(9, 0))
        self.app.label(setup, '任務目標', role='panel').pack(anchor='w')
        self.goal = tk.Text(setup, height=4, wrap='word', relief='flat', bd=0, padx=10, pady=8,
                            font=(self.app.ui_font, 11), undo=True)
        self.app.roles.append((self.goal, 'input', 'ink'))
        self.goal.pack(fill='x', pady=(5, 10))
        self.goal.bind('<Control-Return>', lambda _: (self.start(), 'break')[1])
        actions = self.app.frame(setup, role='panel')
        actions.pack(fill='x')
        self.start_button = ttk.Button(actions, text='開始任務', command=self.start, style='Primary.TButton')
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(actions, text='停止', command=self.cancel, state='disabled', style='Outline.TButton')
        self.stop_button.pack(side='left', padx=8)
        self.app.label(actions, textvariable=self.status, role='panel', color='muted',
                       anchor='w', justify='left', wraplength=520).pack(side='left', padx=12, fill='x', expand=True)

        result_frame = self.app.frame(self.center, role='chat', padx=14, pady=12, highlightthickness=1)
        result_frame.pack(fill='both', expand=True, pady=(12, 0))
        self.app.label(result_frame, '執行紀錄', role='chat', color='accent').pack(anchor='w', pady=(0, 8))
        self.output = tk.Text(result_frame, wrap='word', state='disabled', relief='flat', bd=0,
                              padx=10, pady=9, font=(self.app.ui_font, 10), cursor='xterm')
        self.app.roles.append((self.output, 'chat', 'ink'))
        self.output.pack(fill='both', expand=True)
        self.output_bar = ttk.Scrollbar(result_frame, command=self.output.yview)
        self.output.configure(yscrollcommand=self._scroll_output)
        self.output.tag_configure('heading', font=(self.app.ui_font, 11, 'bold'))
        self.output.tag_configure('muted', font=(self.app.ui_font, 9))

    def _scroll_output(self, first, last):
        self.output_bar.set(first, last)
        needed = float(first) > .0001 or float(last) < .9999
        if needed and not self.output_bar.winfo_manager():
            self.output_bar.pack(side='right', fill='y', before=self.output)
        elif not needed and self.output_bar.winfo_manager():
            self.output_bar.pack_forget()

    def apply_theme(self, palette):
        self.menu.configure(bg=palette['panel'], fg=palette['ink'], activebackground=palette['selected'],
                            activeforeground=palette['ink'], font=(self.app.ui_font, 10))
        self.output.tag_configure('heading', foreground=palette['accent'])
        self.output.tag_configure('muted', foreground=palette['muted'])
        self.refresh_tasks()

    def switch(self, mode):
        if mode not in ('chat', 'agent') or mode == self.mode:
            return
        self.mode = mode
        if mode == 'agent':
            self.chat_sidebar.pack_forget()
            self.chat_center.pack_forget()
            self.sidebar.pack(fill='both', expand=True)
            self.center.pack(fill='both', expand=True)
            self.goal.focus_set()
        else:
            self.sidebar.pack_forget()
            self.center.pack_forget()
            self.chat_sidebar.pack(fill='both', expand=True)
            self.chat_center.pack(fill='both', expand=True)
            self.app.input.focus_set()
        self.app.chat_tab.configure(style='ActiveTab.TButton' if mode == 'chat' else 'Tab.TButton')
        self.app.agent_tab.configure(style='ActiveTab.TButton' if mode == 'agent' else 'Tab.TButton')

    def refresh_tasks(self):
        self.tasks = list_tasks()
        for widget in self.list_body.winfo_children():
            widget.destroy()
        self.app.roles = [(widget, bg, fg) for widget, bg, fg in self.app.roles if widget.winfo_exists()]
        for record in self.tasks:
            active = self.task and self.task['id'] == record['id']
            role = 'selected' if active else 'panel'
            card = self.app.frame(self.list_body, role=role, padx=8, pady=8,
                                  highlightthickness=1 if active else 0)
            card.pack(fill='x', pady=2)
            title = record.get('title', 'Agent 任務')
            label = self.app.label(card, title[:34] + ('…' if len(title) > 34 else ''),
                                   role=role, anchor='w', justify='left', wraplength=185)
            label.pack(fill='x')
            state = {'done': '已完成', 'running': '上次中斷', 'cancelled': '已停止',
                     'error': '失敗'}.get(record.get('status'), '未開始')
            if self.runner and self.task['id'] == record['id']:
                state = '執行中'
            note = self.app.label(card, state, role=role, color='muted', anchor='w')
            note.pack(fill='x', pady=(3, 0))
            for widget in (card, label, note):
                widget.bind('<Button-1>', lambda _, identifier=record['id']: self.select(identifier))
                widget.bind('<Button-3>', lambda event, identifier=record['id']: self.show_menu(identifier, event))
        if not self.tasks:
            self.app.label(self.list_body, '尚無 Agent 任務', role='panel', color='muted').pack(anchor='w', pady=12)
        if not self.list_body.winfo_children():
            self.list_body.configure(height=1)
        if self.app.last_theme:
            from opti_ui import paint_roles
            paint_roles(self.app, self.app.last_theme)

    def new(self):
        if self.runner:
            self.status.set('請先停止目前的任務。')
            return
        self.task = new_task()
        self.folder.set('')
        self.goal.delete('1.0', 'end')
        self.status.set('輸入任務目標後按「開始任務」。')
        self.render()
        self.refresh_tasks()
        self.goal.focus_set()

    def select(self, identifier):
        if self.runner:
            self.status.set('請先停止目前的任務。')
            return
        record = next((item for item in self.tasks if item['id'] == identifier), None)
        if record is None:
            return
        self.task = deepcopy(record)
        if self.task['status'] == 'running':
            self.task['status'] = 'cancelled'
            save_task(self.task)
        self.folder.set(self.task.get('folder', ''))
        self.goal.delete('1.0', 'end')
        self.goal.insert('1.0', self.task.get('prompt', ''))
        self.status.set('已開啟 Agent 任務紀錄。')
        self.render()
        self.refresh_tasks()

    def show_menu(self, identifier, event):
        self.menu.delete(0, 'end')
        self.menu.add_command(label='重新命名', command=lambda: self.rename(identifier))
        self.menu.add_command(label='刪除任務', command=lambda: self.delete(identifier))
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()
        return 'break'

    def rename(self, identifier):
        record = next((item for item in self.tasks if item['id'] == identifier), None)
        if record is None:
            return
        title = self.app.prompt('重新命名 Agent 任務', '任務標題：', record['title'])
        if title is None or not title.strip():
            return
        record['title'] = title.strip()[:100]
        save_task(record)
        if self.task['id'] == identifier:
            self.task['title'] = record['title']
        self.refresh_tasks()

    def delete(self, identifier):
        if self.runner and self.task['id'] == identifier:
            self.status.set('請先停止目前的任務。')
            return
        if not self.app.confirm('刪除 Agent 任務', '此任務及其執行紀錄將被刪除，無法復原。'):
            return
        delete_task(identifier)
        if self.task['id'] == identifier:
            self.task = new_task()
            self.goal.delete('1.0', 'end')
            self.folder.set('')
            self.render()
        self.refresh_tasks()

    def choose_folder(self):
        if self.runner:
            return
        path = filedialog.askdirectory(parent=self.app.root, title='選擇 Agent 工作資料夾',
                                       initialdir=self.folder.get() or str(Path.home()))
        if path:
            self.folder.set(path)

    def _append(self, content, tag=None):
        self.output.configure(state='normal')
        self.output.insert('end', content, tag or ())
        self.output.configure(state='disabled')
        self.output.see('end')

    def render(self):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')
        if not self.task.get('prompt'):
            self._append('選擇資料夾並輸入任務，Agent 的每一步都會顯示在這裡。\n', 'muted')
            return
        self._append('任務：' + self.task['prompt'] + '\n\n', 'heading')
        for step in self.task.get('steps', []):
            self._show_step(step)
        if self.task.get('result'):
            self._append('結果\n', 'heading')
            self._append(self.task['result'] + '\n')
        if self.task.get('error'):
            self._append('執行失敗：' + self.task['error'] + '\n')

    def _show_step(self, step):
        name = ACTION_NAMES.get(step['action'], step['action'])
        detail = step.get('path') or '.'
        if step.get('query'):
            detail += ' · ' + step['query']
        if step.get('sheet'):
            detail += ' · ' + step['sheet']
        if step.get('page'):
            detail += ' · 第 ' + step['page'] + ' 頁'
        self._append(f'步驟 {step["number"]} · {name} · {detail}\n', 'heading')
        self._append(step['result'] + '\n\n')

    def start(self):
        if self.runner:
            return
        goal = self.goal.get('1.0', 'end-1c').strip()
        if not goal:
            self.status.set('請先輸入任務目標。')
            return
        if not self.app.ready or self.app.model_loading:
            self.status.set('請等待本機模型載入完成。')
            return
        if self.app.busy or self.app.pdf_job or self.app.speech_job:
            self.status.set('請等待聊天、PDF 或語音工作完成。')
            return
        profile = deepcopy(self.app.settings['text'])
        if profile['model'] not in model_choices(self.app.catalog, 'text'):
            self.status.set('聊天模型未安裝；請先到設定選擇或下載。')
            return
        folder = self.folder.get().strip()
        try:
            runner = AgentRunner(folder, self._model_call, self._emit, self._approve)
        except ValueError as error:
            self.status.set(str(error))
            return
        if self.task['status'] != 'draft':
            self.task = new_task()
        self.task['prompt'] = goal
        self.task['folder'] = folder
        self.task['status'] = 'running'
        self.task['steps'] = []
        self.task['result'] = ''
        self.task['error'] = ''
        if self.task['title'] == self.task['created'][:16].replace('T', ' '):
            self.task['title'] = goal[:32]
        save_task(self.task)
        self.runner = runner
        self.profile = profile
        self.vision_profile = deepcopy(self.app.settings['vision'])
        self.catalog = deepcopy(self.app.catalog)
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.folder_button.configure(state='disabled')
        self.goal.configure(state='disabled')
        self.render()
        self.refresh_tasks()
        threading.Thread(target=self._worker, args=(runner, goal), daemon=True).start()

    def _model_call(self, messages, cancelled):
        kind, host, model, options, routed = route_messages(
            {'text': self.profile, 'vision': self.vision_profile}, messages, 'text', self.catalog)
        service = model_service_kind(model, self.catalog)
        ensure_model_service(service, self.profile['device'])
        info = next((item for item in self.catalog if item['name'] == model), {})
        request = StreamRequest(host, model, options,
                                think=False if 'thinking' in info.get('capabilities', []) else None)
        self.request = request
        chunks = []
        try:
            if cancelled.is_set():
                request.cancel()
            request.stream(routed, lambda event, value: chunks.append(value) if event == 'token' else None)
        finally:
            self.request = None
        return ''.join(chunks)

    def _emit(self, event, value):
        self.app.extra.put(('agent_event', (self.runner, event, value)))

    def _approve(self, preview, cancelled):
        answer = {'value': False}
        ready = threading.Event()
        self.app.extra.put(('agent_event', (self.runner, 'approval', (preview, answer, ready))))
        while not ready.wait(.1):
            if cancelled.is_set():
                return False
        return answer['value'] and not cancelled.is_set()

    def _worker(self, runner, goal):
        try:
            runner.run(goal)
            outcome = 'cancelled' if runner.cancelled.is_set() else 'done'
            detail = ''
        except Exception as error:
            outcome, detail = ('cancelled', '') if runner.cancelled.is_set() else ('error', str(error))
        self.app.extra.put(('agent_event', (runner, 'complete', (outcome, detail))))

    def handle_event(self, value):
        runner, event, payload = value
        if runner is not self.runner:
            return
        if event == 'status':
            self.status.set(payload)
        elif event == 'approval':
            preview, answer, ready = payload
            try:
                if not runner.cancelled.is_set():
                    answer['value'] = bool(self.app.confirm('確認 Agent 編輯文件', preview))
            finally:
                ready.set()
        elif event == 'step':
            self.task['steps'].append(payload)
            save_task(self.task)
            self._show_step(payload)
        elif event == 'final':
            self.task['result'] = payload
            save_task(self.task)
            self._append('結果\n', 'heading')
            self._append(payload + '\n')
        elif event == 'complete':
            outcome, detail = payload
            self.task['status'] = outcome
            self.task['error'] = detail
            save_task(self.task)
            self.runner = None
            self.request = None
            self.start_button.configure(state='normal')
            self.stop_button.configure(state='disabled')
            self.folder_button.configure(state='normal')
            self.goal.configure(state='normal')
            self.status.set({'done': 'Agent 任務已完成。', 'cancelled': 'Agent 任務已停止。',
                             'error': 'Agent 任務失敗：' + detail}.get(outcome, 'Agent 已停止。'))
            if detail:
                self._append('執行失敗：' + detail + '\n')
            self.refresh_tasks()

    def cancel(self):
        if self.runner:
            self.runner.cancel()
            if self.request:
                self.request.cancel()
            self.status.set('正在停止 Agent 任務…')

    def shutdown(self):
        if self.runner:
            self.cancel()
            self.task['status'] = 'cancelled'
            save_task(self.task)
