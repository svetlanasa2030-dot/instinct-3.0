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
        self.geometry("820x900")
        self.resizable(False, False)
        self.running = False
        self.fields = {}
        self._build()

    def _field(self, parent, label, key, secret=False, default=""):
        ttk.Label(parent, text=label).pack(anchor="w", padx=18, pady=(7, 2))
        var = tk.StringVar(value=os.getenv(key, default))
        self.fields[key] = var
        ttk.Entry(parent, textvariable=var, show="*" if secret else "").pack(fill="x", padx=18)

    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        ttk.Label(self, text="INSTINCT BOT 3.0", font=("Segoe UI", 20, "bold")).pack(pady=(16, 3))
        ttk.Label(self, text="Telegram + OpenAI + Google Docs").pack(pady=(0, 12))

        conn = ttk.LabelFrame(self, text="Подключения")
        conn.pack(fill="x", padx=18, pady=5)
        self._field(conn, "Telegram Bot Token", "TELEGRAM_BOT_TOKEN", True)
        self._field(conn, "OpenAI API Key", "OPENAI_API_KEY", True)
        self._field(conn, "ID Telegram-группы", "GROUP_CHAT_ID", False, "-3667294272")
        self._field(conn, "Google Docs — база знаний", "GOOGLE_DOCS_URL")
        self._field(conn, "Модель OpenAI", "OPENAI_MODEL", False, "gpt-5.1-mini")

        prompts = ttk.LabelFrame(self, text="Промты")
        prompts.pack(fill="both", expand=False, padx=18, pady=10)

        ttk.Label(prompts, text="Основной промт — правила общения бота:").pack(anchor="w", padx=12, pady=(8, 3))
        self.system_prompt = tk.Text(prompts, height=7, wrap="word")
        self.system_prompt.pack(fill="x", padx=12, pady=(0, 8))
        self.system_prompt.insert("1.0", os.getenv("SYSTEM_PROMPT", ""))

        ttk.Label(prompts, text="Промт инициативы — правила самостоятельных сообщений:").pack(anchor="w", padx=12, pady=(2, 3))
        self.initiative_prompt = tk.Text(prompts, height=5, wrap="word")
        self.initiative_prompt.pack(fill="x", padx=12, pady=(0, 10))
        self.initiative_prompt.insert("1.0", os.getenv("INITIATIVE_PROMPT", ""))

        init = ttk.LabelFrame(self, text="Инициативный диалог")
        init.pack(fill="x", padx=18, pady=10)
        self.enabled = tk.BooleanVar(value=os.getenv("INITIATIVE_ENABLED", "true").lower() == "true")
        ttk.Checkbutton(init, text="Разрешить инициативные сообщения", variable=self.enabled).pack(anchor="w", padx=18, pady=8)
        row = ttk.Frame(init)
        row.pack(anchor="w", padx=18, pady=(0, 10))
        ttk.Label(row, text="Постоянный интервал, минут:").pack(side="left")
        self.interval = tk.StringVar(value=os.getenv("INITIATIVE_INTERVAL_MINUTES", "60"))
        ttk.Entry(row, textvariable=self.interval, width=8).pack(side="left", padx=10)

        self.status = ttk.Label(self, text="● Бот остановлен")
        self.status.pack(anchor="w", padx=18, pady=5)

        buttons = ttk.Frame(self)
        buttons.pack(pady=10)
        ttk.Button(buttons, text="▶ Запустить", command=self.start).pack(side="left", padx=5)
        ttk.Button(buttons, text="■ Остановить", command=self.stop).pack(side="left", padx=5)
        ttk.Button(buttons, text="↻ Обновить Google Docs", command=self.refresh).pack(side="left", padx=5)
        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="left", padx=5)
        ttk.Button(buttons, text="Проверить Telegram", command=self.check_telegram).pack(side="left", padx=5)
        ttk.Button(buttons, text="Проверить группу", command=self.check_group).pack(side="left", padx=5)

        self.log = tk.Text(self, height=10, width=90, state="disabled")
        self.log.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self.write(f"Настройки хранятся локально: {ENV_PATH}")

    def write(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def save(self, quiet=False):
        try:
            interval = max(1, int(self.interval.get().strip() or "60"))
            self.interval.set(str(interval))
        except ValueError:
            raise ValueError("Интервал должен быть целым числом минут.")
        values = {key: var.get().strip() for key, var in self.fields.items()}
        values["INITIATIVE_ENABLED"] = "true" if self.enabled.get() else "false"
        values["INITIATIVE_INTERVAL_MINUTES"] = self.interval.get()
        values["KNOWLEDGE_REFRESH_MINUTES"] = "10"
        values["SYSTEM_PROMPT"] = self.system_prompt.get("1.0", "end-1c")
        values["INITIATIVE_PROMPT"] = self.initiative_prompt.get("1.0", "end-1c")
        save_local_settings(values)
        self.write("✓ Настройки сохранены локально.")
        if not quiet:
            messagebox.showinfo("Instinct Bot", "Настройки сохранены.")

    def refresh(self):
        try:
            self.save(quiet=True)
            from .knowledge import refresh_google_doc
            url = self.fields["GOOGLE_DOCS_URL"].get().strip()
            if not url:
                self.write("⚠ Ссылка Google Docs не указана.")
                return
            ok = refresh_google_doc(url)
            self.write("✓ Google Docs загружен." if ok else "✗ Не удалось загрузить Google Docs. Проверьте доступ по ссылке.")
        except Exception as e:
            self.write(f"✗ Ошибка базы знаний: {e}")


    def check_telegram(self):
        try:
            self.save(quiet=True)
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

            bot_name = asyncio.run(check())
            self.write(f"✓ Telegram Token OK: @{bot_name}")
            messagebox.showinfo("Telegram", f"Бот подключён: @{bot_name}\nТокен действителен.")
        except Exception as e:
            self.write(f"✗ Telegram Token: {e}")
            messagebox.showerror("Telegram — ошибка", str(e))

    def check_group(self):
        try:
            self.save(quiet=True)
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
            self.write(f"✓ Группа найдена: {chat_name} ({self.fields['GROUP_CHAT_ID'].get()})")
            messagebox.showinfo("Telegram-группа", f"Группа найдена:\n{chat_name}\nID: {self.fields['GROUP_CHAT_ID'].get()}")
        except Exception as e:
            self.write(f"✗ Группа: {e}")
            messagebox.showerror("Telegram-группа — ошибка", "Группа не найдена. Проверьте ID и убедитесь, что бот добавлен в группу.\n\n" + str(e))


    def start(self):
        if self.running:
            self.write("Бот уже запущен.")
            return
        try:
            self.save(quiet=True)
            self.refresh()
            self.running = True
            self.status.configure(text="● Бот запускается...")
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
        self.write("Для полной остановки закройте программу.")
        self.status.configure(text="● Бот работает (остановка — закрыть окно)")

if __name__ == "__main__":
    App().mainloop()
