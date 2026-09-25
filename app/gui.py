import asyncio
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from .config import save_local_settings, ENV_PATH, load_settings
# Явный импорт для PyInstaller: main.py загружается динамически из GUI,
# поэтому зависимости main.py иначе могут не попасть в собранный EXE.
from .storage import Storage  # noqa: F401


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Instinct Bot 3.0")
        self.geometry("1280x1100")
        self.minsize(1100, 900)
        self.running = False
        self.fields = {}
        self.status_vars = {}
        self.status_detail_vars = {}
        self._build()

    def _field(self, parent, label, key, secret=False, default=""):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=12, pady=4)
        ttk.Label(row, text=label, width=28).pack(side="left")
        var = tk.StringVar(value=os.getenv(key, default))
        self.fields[key] = var
        ttk.Entry(row, textvariable=var, show="*" if secret else "").pack(side="left", fill="x", expand=True)

    def _connection_card(self, parent, key, title, subtitle, command, icon):
        column = len(self.status_vars)
        card = ttk.Frame(parent, relief="groove", padding=10)
        card.grid(row=0, column=column, sticky="nsew", padx=5, pady=5)
        parent.columnconfigure(column, weight=1)
        self.status_vars[key] = tk.StringVar(value="⚪ Не проверено")
        self.status_detail_vars[key] = tk.StringVar(value=subtitle)
        ttk.Label(card, text=icon, font=("Segoe UI Symbol", 25)).pack(anchor="w")
        ttk.Label(card, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(card, textvariable=self.status_vars[key], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(3, 0))
        ttk.Label(card, textvariable=self.status_detail_vars[key], wraplength=190).pack(anchor="w", pady=(2, 8))
        ttk.Button(card, text="Проверить", command=command).pack(fill="x")

    def _section(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill="x", padx=14, pady=6)
        return frame

    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Action.TButton", font=("Segoe UI", 10, "bold"), padding=6)

        self.geometry("1050x760")
        self.minsize(900, 650)

        header = ttk.Frame(self, padding=(10, 7, 10, 2))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left")
        ttk.Label(left, text="INSTINCT BOT 3.0", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Telegram + OpenAI + Google Docs").pack(anchor="w")
        ttk.Button(header, text="⚙ Настройки", command=self.focus_settings).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=7, pady=(3, 7))

        overview = ttk.Frame(nb, padding=6)
        sources = ttk.Frame(nb, padding=6)
        settings = ttk.Frame(nb, padding=6)
        prompts = ttk.Frame(nb, padding=6)
        initiative = ttk.Frame(nb, padding=6)
        journal = ttk.Frame(nb, padding=6)
        recruits = ttk.Frame(nb, padding=6)
        for frame, title in [
            (overview, "Обзор"), (sources, "📚 Источники"), (settings, "Настройки"),
            (prompts, "Промты"), (initiative, "Инициативный диалог"), (journal, "Журнал"),
            (recruits, "👤 Новички")
        ]:
            nb.add(frame, text=title)

        # --- Обзор: подключения + управление ---
        conn = ttk.LabelFrame(overview, text="Подключения и статус", padding=6)
        conn.pack(fill="x", pady=(0, 6))
        cards = ttk.Frame(conn)
        cards.pack(fill="x")
        self._connection_card(cards, "telegram", "Telegram Bot", "Бот не проверен", self.check_telegram, "✈")
        self._connection_card(cards, "group", "Telegram-группа", "ID не проверен", self.check_group, "👥")
        self._connection_card(cards, "openai", "OpenAI", "Модель не проверена", self.check_openai, "◉")
        self._connection_card(cards, "google", "Google Docs", "База знаний не проверена", self.check_google_docs, "◆")

        control = ttk.LabelFrame(overview, text="Управление ботом", padding=6)
        control.pack(fill="x", pady=(0, 6))
        buttons = ttk.Frame(control)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="▶ Запустить", style="Action.TButton", command=self.start).pack(side="left", fill="x", expand=True, padx=(0, 3))
        ttk.Button(buttons, text="■ Остановить", style="Action.TButton", command=self.stop).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(buttons, text="↻ Обновить Docs", style="Action.TButton", command=self.refresh).pack(side="left", fill="x", expand=True, padx=(3, 0))
        status = ttk.Frame(control, relief="groove", padding=7)
        status.pack(fill="x", pady=(6, 0))
        self.status = ttk.Label(status, text="● Бот остановлен", font=("Segoe UI", 10, "bold"))
        self.status.pack(side="left")
        self.last_activity = ttk.Label(status, text="Последняя активность: —")
        self.last_activity.pack(side="right")

        # --- Источники ---
        sources.columnconfigure(1, weight=1)
        ttk.Label(sources, text="Сайт:").grid(row=0, column=0, sticky="w", padx=(2, 8), pady=4)
        self.source_url = tk.StringVar(value=os.getenv("KNOWLEDGE_SOURCE_URL", ""))
        ttk.Entry(sources, textvariable=self.source_url).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(sources, text="Форум:").grid(row=1, column=0, sticky="w", padx=(2, 8), pady=4)
        self.sitemap_url = tk.StringVar(value=os.getenv("KNOWLEDGE_SITEMAP_URL", ""))
        ttk.Entry(sources, textvariable=self.sitemap_url).grid(row=1, column=1, sticky="ew", pady=4)
        row = ttk.Frame(sources)
        row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        ttk.Button(row, text="🔎 Сканировать сейчас", command=self.scan_sources).pack(side="left")
        self.source_status = tk.StringVar(value="⚪ Источники не проверены")
        ttk.Label(row, textvariable=self.source_status).pack(side="left", padx=10)
        self.source_error = tk.StringVar(value="")
        ttk.Label(sources, textvariable=self.source_error, foreground="red", wraplength=900).grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        page_frame = ttk.LabelFrame(sources, text="Загруженные страницы", padding=4)
        page_frame.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        sources.rowconfigure(4, weight=1)
        page_frame.columnconfigure(0, weight=1)
        page_frame.rowconfigure(0, weight=1)
        self.source_pages = ttk.Treeview(page_frame, columns=("type", "url"), show="headings", height=8)
        self.source_pages.heading("type", text="Источник")
        self.source_pages.heading("url", text="Страница")
        self.source_pages.column("type", width=90, stretch=False)
        self.source_pages.column("url", width=780)
        self.source_pages.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(page_frame, orient="vertical", command=self.source_pages.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.source_pages.configure(yscrollcommand=sb.set)

        # --- Настройки ---
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)
        self._field(settings, "Telegram Bot Token", "TELEGRAM_BOT_TOKEN", True)
        self._field(settings, "OpenAI API Key", "OPENAI_API_KEY", True)
        self._field(settings, "ID Telegram-группы", "GROUP_CHAT_ID")
        self._field(settings, "Модель OpenAI", "OPENAI_MODEL", default="gpt-5.6-luna")
        self._field(settings, "Google Docs — база знаний", "GOOGLE_DOCS_URL")
        ttk.Button(settings, text="💾 Сохранить настройки", command=self.save).pack(anchor="e", pady=(5, 0))

        # --- Промты ---
        prompts.columnconfigure(0, weight=1)
        prompts.columnconfigure(1, weight=1)
        p1 = ttk.Frame(prompts); p1.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        p2 = ttk.Frame(prompts); p2.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        prompts.rowconfigure(0, weight=1)
        ttk.Label(p1, text="Основной промт").pack(anchor="w")
        self.system_prompt = tk.Text(p1, height=14, wrap="word")
        self.system_prompt.pack(fill="both", expand=True, pady=3)
        self.system_prompt.insert("1.0", os.getenv("SYSTEM_PROMPT", ""))
        ttk.Label(p2, text="Промт инициативы").pack(anchor="w")
        self.initiative_prompt = tk.Text(p2, height=14, wrap="word")
        self.initiative_prompt.pack(fill="both", expand=True, pady=3)
        self.initiative_prompt.insert("1.0", os.getenv("INITIATIVE_PROMPT", ""))

        # --- Инициатива ---
        initiative.columnconfigure(0, weight=1)
        ttk.Label(initiative, text="Автоматические сообщения").grid(row=0, column=0, sticky="w", pady=(2, 8))
        row = ttk.Frame(initiative); row.grid(row=1, column=0, sticky="ew")
        self.enabled = tk.BooleanVar(value=os.getenv("INITIATIVE_ENABLED", "true").lower() == "true")
        ttk.Checkbutton(row, text="Включить инициативные сообщения", variable=self.enabled).pack(side="left")
        ttk.Label(row, text="Интервал (мин.):").pack(side="left", padx=(20, 5))
        self.interval = tk.IntVar(value=max(1, int(os.getenv("INITIATIVE_INTERVAL_MINUTES", "60"))))
        ttk.Spinbox(row, from_=1, to=1440, textvariable=self.interval, width=7).pack(side="left")
        ttk.Button(row, text="✈ Тестовое сообщение", command=self.test_message).pack(side="right")

        # --- Журнал ---
        self.log = tk.Text(journal, height=20, bg="#101214", fg="#e8edf2", insertbackground="white", relief="flat")
        self.log.pack(fill="both", expand=True)
        log_bottom = ttk.Frame(journal); log_bottom.pack(fill="x", pady=(5, 0))
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_bottom, text="Автопрокрутка", variable=self.autoscroll).pack(side="left")
        ttk.Button(log_bottom, text="🗑 Очистить лог", command=self.clear_log).pack(side="right")
        # --- Новички ---
        recruits.columnconfigure(0, weight=1)
        recruits.rowconfigure(1, weight=1)

        recruits_top = ttk.Frame(recruits)
        recruits_top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(
            recruits_top,
            text="Принятые новички",
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")
        self.recruits_count = tk.StringVar(value="Всего: 0")
        ttk.Label(recruits_top, textvariable=self.recruits_count).pack(side="left", padx=12)
        ttk.Button(
            recruits_top,
            text="↻ Обновить",
            command=self.refresh_recruits,
        ).pack(side="right")

        recruits_table = ttk.Frame(recruits)
        recruits_table.grid(row=1, column=0, sticky="nsew")
        recruits_table.columnconfigure(0, weight=1)
        recruits_table.rowconfigure(0, weight=1)

        columns = (
            "nickname", "level", "class", "teamspeak",
            "telegram", "accepted_by", "date"
        )
        self.recruits_tree = ttk.Treeview(
            recruits_table,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "nickname": "Игровой ник",
            "level": "Уровень",
            "class": "Класс",
            "teamspeak": "TeamSpeak",
            "telegram": "Telegram",
            "accepted_by": "Кто принял",
            "date": "Дата",
        }
        widths = {
            "nickname": 180, "level": 80, "class": 130,
            "teamspeak": 100, "telegram": 100,
            "accepted_by": 160, "date": 150,
        }
        for column in columns:
            self.recruits_tree.heading(column, text=headings[column])
            self.recruits_tree.column(column, width=widths[column], minwidth=70, stretch=True)

        y_scroll = ttk.Scrollbar(recruits_table, orient="vertical", command=self.recruits_tree.yview)
        x_scroll = ttk.Scrollbar(recruits_table, orient="horizontal", command=self.recruits_tree.xview)
        self.recruits_tree.configure(
            yscrollcommand=y_scroll.set,
            xscrollcommand=x_scroll.set,
        )
        self.recruits_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        # При каждом запуске сразу открываем вкладку «Новички».
        # Данные в ней уже загружаются из локальной базы.
        nb.select(recruits)

        self.write("[Система] Приложение запущено")
        self.write("[Система] Все настройки загружены")
        self.write("[Статус] Бот остановлен")
        self.refresh_recruits()

    def refresh_recruits(self):
        """Показывает локально сохранённых новичков из SQLite."""
        try:
            settings = load_settings()
            storage = Storage(settings.db_path)
            rows = storage.all_recruits()

            for item in self.recruits_tree.get_children():
                self.recruits_tree.delete(item)

            for nickname, level, class_name, teamspeak, telegram, username, display_name, created_at in rows:
                accepted_by = f"@{username}" if username else (display_name or "—")
                try:
                    date_text = datetime.fromisoformat(created_at).astimezone().strftime("%d.%m.%Y %H:%M")
                except Exception:
                    date_text = (created_at or "")[:16].replace("T", " ")

                self.recruits_tree.insert(
                    "",
                    "end",
                    values=(
                        nickname or "—",
                        level or "—",
                        class_name or "—",
                        teamspeak or "—",
                        telegram or "—",
                        accepted_by,
                        date_text,
                    ),
                )

            self.recruits_count.set(f"Всего: {len(rows)}")
            self.write(f"[Новички] Загружено записей: {len(rows)}")
        except Exception as exc:
            self.recruits_count.set("Ошибка загрузки")
            self.write(f"[Новички] Ошибка: {exc}")

    def scan_sources(self):
        site_url = self.source_url.get().strip()
        forum_url = self.sitemap_url.get().strip()
        urls = []
        if site_url:
            urls.append(site_url)
        if forum_url:
            urls.append(forum_url)
        if not urls:
            messagebox.showwarning("Источники знаний", "Укажите сайт или форум.")
            return
        self.save(quiet=True)
        self.source_status.set("🟡 Сканирование...")
        self.source_error.set("")
        self.write("[Источники] Начато сканирование сайта и форума")
        def worker():
            try:
                from .source_sync import collect_sources
                def progress(root, loaded, seen, pending, error, current_url=""):
                    label = "Форум" if "forum." in root.lower() or "/forum" in root.lower() else "Сайт"
                    msg = f"🟡 {label}: загружено {loaded} | найдено ссылок: {seen} | очередь: {pending}"
                    if error:
                        msg += f" | ошибка: {error[:100]}"
                    self.after(0, lambda msg=msg: self.source_status.set(msg))
                    if current_url and not error:
                        self.after(0, lambda u=current_url, l=label: self._add_source_page(l, u))
                    if error:
                        self.after(0, lambda msg=msg: self.write(f"[Источники] {label}: {msg}"))
                self.after(0, lambda: [self.source_pages.delete(x) for x in self.source_pages.get_children()])
                total, details = collect_sources(urls, max_pages=20000, progress=progress)
                summary = " | ".join(
                    f"{'Форум' if ('forum.' in root.lower() or '/forum' in root.lower()) else 'Сайт'}: {count}"
                    for root, count, _ in details
                )
                self.after(0, lambda: self.source_status.set(f"🟢 Загружено страниц: {total}"))
                if forum_url:
                    summary += " | Форум: поиск по поисковику при вопросе"
                self.after(0, lambda: self.source_error.set(summary))
                self.after(0, lambda: self.write(f"[Источники] Сканирование завершено: {summary}"))
            except Exception as e:
                self.after(0, lambda: self.source_status.set("🔴 Ошибка"))
                self.after(0, lambda e=e: self.source_error.set(f"Ошибка сканирования: {e}"))
                self.after(0, lambda e=e: self.write(f"[Источники] Ошибка: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _add_source_page(self, label, url):
        if not hasattr(self, "source_pages"):
            return
        # Не забиваем интерфейс тысячами строк: показываем последние 300 страниц.
        existing = {self.source_pages.item(i, "values")[1] for i in self.source_pages.get_children()}
        if url in existing:
            return
        self.source_pages.insert("", "end", values=(label, url))
        rows = self.source_pages.get_children()
        if len(rows) > 300:
            self.source_pages.delete(rows[0])

    def focus_settings(self):
        self.write("[Система] Раздел настроек доступен ниже")

    def clear_log(self):
        self.log.delete("1.0", "end")

    def test_message(self):
        self.write("[Тест] Тестовое сообщение вызвано")

    def write(self, msg):
        self.log.insert("end", msg + "\n")
        if self.autoscroll.get():
            self.log.see("end")

    def set_status(self, key, text, detail=None):
        if key not in self.status_vars:
            return
        self.after(0, lambda: self.status_vars[key].set(text))
        if detail is not None:
            self.after(0, lambda: self.status_detail_vars[key].set(detail))

    def save(self, quiet=False):
        values = {key: var.get().strip() for key, var in self.fields.items()}
        values["INITIATIVE_ENABLED"] = "true" if self.enabled.get() else "false"
        values["INITIATIVE_INTERVAL_MINUTES"] = str(max(1, int(self.interval.get())))
        values["KNOWLEDGE_REFRESH_MINUTES"] = "10"
        values["KNOWLEDGE_SOURCE_URL"] = self.source_url.get().strip()
        values["KNOWLEDGE_SITEMAP_URL"] = self.sitemap_url.get().strip()
        values["SYSTEM_PROMPT"] = self.system_prompt.get("1.0", "end-1c")
        values["INITIATIVE_PROMPT"] = self.initiative_prompt.get("1.0", "end-1c")
        save_local_settings(values)
        self.write("✓ Настройки сохранены локально.")
        if not quiet:
            messagebox.showinfo("Instinct Bot", "Настройки сохранены.")

    def _run_check(self, name, worker):
        self.set_status(name, "🟡 Проверка...", "Идёт проверка подключения")
        threading.Thread(target=self._check_worker, args=(name, worker), daemon=True).start()

    def _check_worker(self, name, worker):
        try:
            result = worker()
            self.set_status(name, "🟢 Подключен", result)
            self.after(0, lambda: self.write(f"✓ {name}: {result}"))
        except Exception as e:
            self.set_status(name, "🔴 Ошибка", str(e)[:120])
            self.after(0, lambda: self.write(f"✗ {name}: {e}"))

    def check_telegram(self):
        self.save(quiet=True)
        def worker():
            from aiogram import Bot
            from .config import load_settings
            async def check():
                settings = load_settings()
                bot = Bot(settings.telegram_token)
                try:
                    me = await bot.get_me()
                    return f"Бот: @{me.username or me.first_name}"
                finally:
                    await bot.session.close()
            return asyncio.run(check())
        self._run_check("telegram", worker)

    def check_group(self):
        self.save(quiet=True)
        def worker():
            from aiogram import Bot
            from .config import load_settings
            async def check():
                settings = load_settings()
                bot = Bot(settings.telegram_token)
                try:
                    chat = await bot.get_chat(settings.group_chat_id)
                    return f"ID: {chat.id} • {chat.title or 'Чат'}"
                finally:
                    await bot.session.close()
            return asyncio.run(check())
        self._run_check("group", worker)

    def check_openai(self):
        self.save(quiet=True)
        def worker():
            from openai import OpenAI
            from .config import load_settings
            settings = load_settings()
            model = self.fields["OPENAI_MODEL"].get().strip() or settings.openai_model
            OpenAI(api_key=settings.openai_key).models.retrieve(model)
            return f"Модель: {model}"
        self._run_check("openai", worker)

    def check_google_docs(self):
        self.save(quiet=True)
        def worker():
            from .knowledge import refresh_google_doc
            url = self.fields["GOOGLE_DOCS_URL"].get().strip()
            if not url:
                raise ValueError("Ссылка Google Docs не указана")
            if not refresh_google_doc(url):
                raise RuntimeError("Не удалось загрузить Google Docs")
            return "База знаний обновлена"
        self._run_check("google", worker)

    def refresh(self):
        self.check_google_docs()

    def start(self):
        if self.running:
            self.write("[Бот] Уже запущен")
            return
        try:
            self.save(quiet=True)
            self.running = True
            self.status.configure(text="●  Бот запускается...")
            self.write("▶ Запуск бота...")
            threading.Thread(target=self._run_bot, daemon=True).start()
        except Exception as e:
            self.running = False
            self.status.configure(text="●  Ошибка")
            messagebox.showerror("Ошибка", str(e))

    def _run_bot(self):
        try:
            from .main import main

            async def run():
                await main()

            asyncio.run(run())
        except Exception as e:
            self.after(0, lambda: self.write(f"✗ Ошибка бота: {e}"))
            self.after(0, lambda: self.status.configure(text="●  Ошибка"))
        finally:
            self.running = False

    def stop(self):
        if not self.running:
            self.write("[Бот] Уже остановлен")
            return
        self.write("⏹ Остановка запрошена.")
        self.status.configure(text="●  Останавливается...")
        try:
            from .main import request_stop
            request_stop()
        except Exception as e:
            self.write(f"✗ Ошибка остановки: {e}")


if __name__ == "__main__":
    App().mainloop()
