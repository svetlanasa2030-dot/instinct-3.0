# Google Sheets для анкеты новичков

1. Создайте Google Таблицу и скопируйте ID из адреса: https://docs.google.com/spreadsheets/d/ЭТОТ_ID/edit
2. Откройте Расширения -> Apps Script.
3. Вставьте код из google_apps_script/Code.gs.
4. В Code.gs замените PASTE_SHEET_ID_HERE на ID вашей таблицы.
5. В Code.gs замените PASTE_THE_SAME_KEY_AS_BOT_CONFIG на выбранный длинный случайный ключ.
6. В боте этот же ключ укажите как GOOGLE_NEWBIE_SECRET.
7. Разверните Apps Script как Веб-приложение: выполнять от имени Я, доступ — Все.
8. Скопируйте URL развёртывания, заканчивающийся на /exec.
9. В %APPDATA%\InstinctBot\.env добавьте GOOGLE_NEWBIE_WEBHOOK с этим URL.
10. Перезапустите бота.
11. Откройте /newbie и нажмите «☁️ Тест Google Sheets».

При успешном тесте будет создан лист «Новички» и добавлена строка TEST.
После этого подтверждённые анкеты будут сохраняться и в SQLite, и в Google Sheets.

Важно: GOOGLE_NEWBIE_SECRET и URL Web App не публикуйте в GitHub.