import asyncio
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .config import save_local_settings, ENV_PATH


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Instinct Bot 3.0")
        self.geometry("1280x980")
        self.minsize(1100, 820)
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
        style.configure("Title.TLabel", font=("Segoe UI", 26, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 11))
        style.configure("Action.TButton", font=("Segoe UI", 11, "bold"), padding=10)

        header = ttk.Frame(self, padding=(14, 10, 14, 2))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left")
        ttk.Label(left, text="INSTINCT BOT 3.0", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Telegram + OpenAI + Google Docs", style="Subtitle.TLabel").pack(anchor="w")
        ttk.Button(header, text="⚙ Настройки", command=self.focus_settings).pack(side="right", ipadx=8, ipady=3)

        conn = self._section(self, "Подключения и статус")
        cards = ttk.Frame(conn)
        cards.pack(fill="x")
        self._connection_card(cards, "telegram", "Telegram Bot", "Бот не проверен", self.check_telegram, "✈")
        self._connection_card(cards, "group", "Telegram-группа", "ID не проверен", self.check_group, "👥")
        self._connection_card(cards, "openai", "OpenAI", "Модель не проверена", self.check_openai, "◉")
        self._connection_card(cards, "google", "Google Docs", "База знаний не проверена", self.check_google_docs, "◆")

        control = self._section(self, "Управление ботом")
        buttons = ttk.Frame(control)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="▶  Запустить бота", style="Action.TButton", command=self.start).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(buttons, text="■  Остановить бота", style="Action.TButton", command=self.stop).pack(side="left", fill="x", expand=True, padx=3)
        ttk.Button(buttons, text="↻  Обновить Google Docs", style="Action.TButton", command=self.refresh).pack(side="left", fill="x", expand=True, padx=(6, 0))
        status = ttk.Frame(control, relief="groove", padding=10)
        status.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(status, text="●  Бот остановлен", font=("Segoe UI", 11, "bold"))
        self.status.pack(side="left")
        self.last_activity = ttk.Label(status, text="Последняя активность: —")
        self.last_activity.pack(side="right")

        sources = self._section(self, "📚 Источники знаний")
        ttk.Label(sources, text="Вставь ссылки списком — по одной ссылке в строке. Программа обработает их по очереди.").pack(anchor="w", padx=12)
        self.sources_text = tk.Text(sources, height=7, wrap="word")
        self.sources_text.pack(fill="x", padx=12, pady=5)
        self.sources_text.insert("1.0", os.getenv("KNOWLEDGE_SOURCES", ""))
        row = ttk.Frame(sources); row.pack(fill="x", padx=12, pady=(0,5))
        ttk.Button(row, text="➕ Добавить ссылки", command=self.add_sources).pack(side="left")
        ttk.Button(row, text="▶ Парсить все ссылки", command=self.parse_all_sources).pack(side="left", padx=8)
        self.source_status = tk.StringVar(value="⚪ Ссылки не обработаны")
        ttk.Label(row, textvariable=self.source_status).pack(side="left", padx=8)
        ttk.Label(sources, text="Результат сохраняется в локальную базу знаний. Google Docs используется ботом как подключённая база для чтения.").pack(anchor="w", padx=12, pady=(0,5))
        settings = self._section(self, "Настройки")
        left = ttk.Frame(settings)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right = ttk.Frame(settings)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._field(left, "Telegram Bot Token", "TELEGRAM_BOT_TOKEN", True)
        self._field(left, "OpenAI API Key", "OPENAI_API_KEY", True)
        self._field(left, "ID Telegram-группы", "GROUP_CHAT_ID")
        self._field(right, "Модель OpenAI", "OPENAI_MODEL", default="gpt-5.6-luna")
        self._field(right, "Google Docs — база знаний", "GOOGLE_DOCS_URL")
        ttk.Button(settings, text="💾 Сохранить настройки", command=self.save).pack(anchor="e", pady=(8, 0))

        prompts = self._section(self, "Промты")
        prompt_grid = ttk.Frame(prompts)
        prompt_grid.pack(fill="x")
        prompt_grid.columnconfigure(0, weight=1)
        prompt_grid.columnconfigure(1, weight=1)
        p1 = ttk.Frame(prompt_grid)
        p1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        p2 = ttk.Frame(prompt_grid)
        p2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(p1, text="Основной промт — правила общения бота:").pack(anchor="w", pady=(0, 3))
        self.system_prompt = tk.Text(p1, height=5, wrap="word")
        self.system_prompt.pack(fill="x")
        self.system_prompt.insert("1.0", os.getenv("SYSTEM_PROMPT", ""))
        ttk.Label(p2, text="Промт инициативы — правила самостоятельных сообщений:").pack(anchor="w", pady=(0, 3))
        self.initiative_prompt = tk.Text(p2, height=5, wrap="word")
        self.initiative_prompt.pack(fill="x")
        self.initiative_prompt.insert("1.0", os.getenv("INITIATIVE_PROMPT", ""))

        init = self._section(self, "Инициативный диалог")
        row = ttk.Frame(init)
        row.pack(fill="x")
        self.enabled = tk.BooleanVar(value=os.getenv("INITIATIVE_ENABLED", "true").lower() == "true")
        ttk.Checkbutton(row, text="Включить инициативные сообщения", variable=self.enabled).pack(side="left", padx=4)
        ttk.Label(row, text="Интервал (минут):").pack(side="left", padx=(24, 6))
        self.interval = tk.IntVar(value=max(1, int(os.getenv("INITIATIVE_INTERVAL_MINUTES", "60"))))
        ttk.Spinbox(row, from_=1, to=1440, textvariable=self.interval, width=8).pack(side="left")
        ttk.Button(row, text="✈ Тестовое сообщение", command=self.test_message).pack(side="right")

        log_frame = self._section(self, "Журнал")
        self.log = tk.Text(log_frame, height=8, bg="#101214", fg="#e8edf2", insertbackground="white", relief="flat")
        self.log.pack(fill="both", expand=True)
        log_bottom = ttk.Frame(log_frame)
        log_bottom.pack(fill="x", pady=(5, 0))
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_bottom, text="Автопрокрутка", variable=self.autoscroll).pack(side="left")
        ttk.Button(log_bottom, text="🗑 Очистить лог", command=self.clear_log).pack(side="right")
        self.write("[Система] Приложение запущено")
        self.write("[Система] Все настройки загружены")
        self.write("[Статус] Бот остановлен")

    def add_sources(self):
        self.sources_text.insert("end", ("\n" if self.sources_text.get("1.0","end-1c").strip() else "") + "https://")

    def parse_all_sources(self):
        urls=[x.strip() for x in self.sources_text.get("1.0","end-1c").splitlines() if x.strip()]
        if not urls:
            messagebox.showwarning("Источники знаний", "Вставьте хотя бы одну ссылку.")
            return
        self.save(quiet=True)
        self.source_status.set(f"🟡 0/{len(urls)}")
        def worker():
            try:
                from .source_sync import scan_pages_sequential
                n=scan_pages_sequential(urls, progress=lambda done,total:self.after(0,lambda done=done,total=total:self.source_status.set(f"🟡 {done}/{total}")))
                self.after(0,lambda:self.source_status.set(f"🟢 Обработано: {n}/{len(urls)}"))
                self.after(0,lambda:self.write(f"[Источники] Обработано: {n}/{len(urls)}"))
            except Exception as e:
                self.after(0,lambda:self.source_status.set("🔴 Ошибка"))
                self.after(0,lambda e=e:self.write(f"[Источники] Ошибка: {e}"))
        threading.Thread(target=worker,daemon=True).start()

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
