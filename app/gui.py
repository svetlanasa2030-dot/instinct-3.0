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
        self.geometry("900x780")
        self.minsize(860, 700)
        self.resizable(True, True)
        self.running = False
        self.fields = {}
        self.status_vars = {}
        self._build()

    def _field(self, parent, label, key, secret=False, default=""):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=12, pady=3)

        ttk.Label(row, text=label, width=24).pack(side="left")
        var = tk.StringVar(value=os.getenv(key, default))
        self.fields[key] = var
        ttk.Entry(row, textvariable=var, show="*" if secret else "").pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        return row

    def _connection_status(self, parent, key, label, command):
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=12, pady=2)

        self.status_vars[key] = tk.StringVar(value="⚪ Не проверено")
        ttk.Label(row, text=label, width=24).pack(side="left")
        ttk.Label(row, textvariable=self.status_vars[key], width=25).pack(side="left")
        ttk.Button(row, text="Проверить", command=command).pack(side="left")
        return row

    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        ttk.Label(
            self, text="INSTINCT BOT 3.0", font=("Segoe UI", 20, "bold")
        ).pack(pady=(10, 2))
        ttk.Label(self, text="Telegram + OpenAI + Gemini + Google Docs").pack(pady=(0, 8))

        conn = ttk.LabelFrame(self, text="Подключения и статус")
        conn.pack(fill="x", padx=14, pady=4)

        self._field(conn, "Telegram Bot Token", "TELEGRAM_BOT_TOKEN", True)
        self._field(conn, "OpenAI API Key", "OPENAI_API_KEY", True)
        self._field(conn, "Gemini API Key", "GEMINI_API_KEY", True)
        self._field(conn, "Модель Gemini", "GEMINI_MODEL", False, "gemini-2.5-flash")
        self._field(conn, "ИИ для ответов (openai/gemini)", "AI_PROVIDER", False, "gemini")
        self._field(conn, "ID Telegram-группы", "GROUP_CHAT_ID", False, "-3667294272")
        self._field(conn, "Google Docs — база знаний", "GOOGLE_DOCS_URL")
        self._field(conn, "Модель OpenAI", "OPENAI_MODEL", False, "gpt-5.1-mini")

        status_frame = ttk.LabelFrame(conn, text="Проверка подключений")
        status_frame.pack(fill="x", padx=8, pady=(5, 8))

        self._connection_status(status_frame, "telegram", "Telegram Bot", self.check_telegram)
        self._connection_status(status_frame, "group", "Telegram-группа", self.check_group)
        self._connection_status(status_frame, "openai", "OpenAI", self.check_openai)
        self._connection_status(status_frame, "gemini", "Gemini", self.check_gemini)
        self._connection_status(status_frame, "google", "Google Docs", self.check_google_docs)

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=14, pady=6)

        ttk.Button(actions, text="▶ Запустить", command=self.start).pack(side="left", padx=3)
        ttk.Button(actions, text="■ Остановить", command=self.stop).pack(side="left", padx=3)
        ttk.Button(actions, text="↻ Обновить Google Docs", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(actions, text="Сохранить", command=self.save).pack(side="left", padx=3)

        self.status = ttk.Label(self, text="● Бот остановлен")
        self.status.pack(anchor="w", padx=18, pady=(0, 5))

        prompts = ttk.LabelFrame(self, text="Промты")
        prompts.pack(fill="x", padx=14, pady=5)

        ttk.Label(prompts, text="Основной промт — правила общения бота:").pack(
            anchor="w", padx=10, pady=(6, 2)
        )
        self.system_prompt = tk.Text(prompts, height=4, wrap="word")
        self.system_prompt.pack(fill="x", padx=10, pady=(0, 6))
        self.system_prompt.insert("1.0", os.getenv("SYSTEM_PROMPT", ""))

        ttk.Label(prompts, text="Промт инициативы — правила самостоятельных сообщений:").pack(
            anchor="w", padx=10, pady=(2, 2)
        )
        self.initiative_prompt = tk.Text(prompts, height=3, wrap="word")
        self.initiative_prompt.pack(fill="x", padx=10, pady=(0, 8))
        self.initiative_prompt.insert("1.0", os.getenv("INITIATIVE_PROMPT", ""))

        init = ttk.LabelFrame(self, text="Инициативный диалог")
        init.pack(fill="x", padx=14, pady=5)
        self.enabled = tk.BooleanVar(
            value=os.getenv("INITIATIVE_ENABLED", "true").lower() == "true"
        )
        ttk.Checkbutton(
            init,
            text="Разрешить инициативные сообщения",
            variable=self.enabled,
        ).pack(anchor="w", padx=14, pady=6)

        log_frame = ttk.LabelFrame(self, text="Журнал")
        log_frame.pack(fill="both", expand=True, padx=14, pady=5)
        self.log = tk.Text(log_frame, height=6, state="disabled")
        self.log.pack(fill="both", expand=True, padx=8, pady=8)

        self.write(f"Настройки хранятся локально: {ENV_PATH}")
        self.write("Статусы подключений: ⚪ Не проверено")

    def write(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_status(self, key, text):
        if key in self.status_vars:
            self.after(0, lambda: self.status_vars[key].set(text))

    def save(self, quiet=False):
        values = {key: var.get().strip() for key, var in self.fields.items()}
        values["INITIATIVE_ENABLED"] = "true" if self.enabled.get() else "false"
        values["KNOWLEDGE_REFRESH_MINUTES"] = "10"
        values["SYSTEM_PROMPT"] = self.system_prompt.get("1.0", "end-1c")
        values["INITIATIVE_PROMPT"] = self.initiative_prompt.get("1.0", "end-1c")
        save_local_settings(values)
        self.write("✓ Настройки сохранены локально.")
        if not quiet:
            messagebox.showinfo("Instinct Bot", "Настройки сохранены.")

    def _run_check(self, name, worker):
        self.set_status(name, "🟡 Проверка...")
        threading.Thread(target=self._check_worker, args=(name, worker), daemon=True).start()

    def _check_worker(self, name, worker):
        try:
            result = worker()
            self.set_status(name, "🟢 OK")
            self.after(0, lambda: self.write(f"✓ {result}"))
        except Exception as e:
            self.set_status(name, "🔴 Ошибка")
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
                    return me.username or me.first_name
                finally:
                    await bot.session.close()

            name = asyncio.run(check())
            return f"Telegram Token OK: @{name}"

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
                    return chat.title or str(chat.id)
                finally:
                    await bot.session.close()

            chat_name = asyncio.run(check())
            return f"Группа найдена: {chat_name}"

        self._run_check("group", worker)

    def check_openai(self):
        self.save(quiet=True)

        def worker():
            from openai import OpenAI
            from .config import load_settings

            settings = load_settings()
            client = OpenAI(api_key=settings.openai_key)
            model = self.fields["OPENAI_MODEL"].get().strip() or settings.openai_model
            client.models.retrieve(model)
            return f"OpenAI OK: {model}"

        self._run_check("openai", worker)

    def check_gemini(self):
        self.save(quiet=True)

        def worker():
            from google import genai

            key = self.fields["GEMINI_API_KEY"].get().strip()
            if not key:
                raise ValueError("Gemini API Key не указан.")
            model = self.fields["GEMINI_MODEL"].get().strip() or "gemini-2.5-flash"
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=model, contents="Ответь одним словом: OK"
            )
            result = (response.text or "").strip()
            if not result:
                raise RuntimeError("Gemini не вернул ответ.")
            return f"Gemini OK: {model}"

        self._run_check("gemini", worker)

    def check_google_docs(self):
        self.save(quiet=True)

        def worker():
            from .knowledge import refresh_google_doc

            url = self.fields["GOOGLE_DOCS_URL"].get().strip()
            if not url:
                raise ValueError("Ссылка Google Docs не указана.")
            if not refresh_google_doc(url):
                raise RuntimeError("Не удалось загрузить Google Docs. Проверьте ссылку и доступ.")
            return "Google Docs OK: база знаний обновлена"

        self._run_check("google", worker)

    def refresh(self):
        self.check_google_docs()

    def start(self):
        if self.running:
            self.write("Бот уже запущен.")
            return
        try:
            self.save(quiet=True)
            self.running = True
            self.status.configure(text="● Бот запускается...")
            self.write("▶ Запуск бота...")
            threading.Thread(target=self._run_bot, daemon=True).start()
        except Exception as e:
            self.running = False
            self.status.configure(text="● Ошибка")
            messagebox.showerror("Ошибка", str(e))

    def _run_bot(self):
        try:
            from .main import main
            asyncio.run(main())
        except Exception as e:
            self.after(0, lambda: self.write(f"✗ Ошибка бота: {e}"))
            self.after(0, lambda: self.status.configure(text="● Ошибка"))
        finally:
            self.running = False

    def stop(self):
        self.write("⚠ Полная остановка бота пока выполняется только при закрытии программы.")
        self.status.configure(text="● Бот работает (остановка — закрыть окно)")


if __name__ == "__main__":
    App().mainloop()
