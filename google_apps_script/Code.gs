const SPREADSHEET_ID = 'PASTE_SHEET_ID_HERE';
const ACCESS_KEY = 'PASTE_THE_SAME_KEY_AS_BOT_CONFIG';
const SHEET_NAME = 'Новички';
const HEADERS = ['Дата','Игровой ник','Уровень','Класс','TeamSpeak','Telegram','Кто принял'];

function doGet() {
  return json_({ok:true, service:'Instinct Google Sheets'});
}

function doPost(e) {
  try {
    const data = JSON.parse(e.postData.contents);
    if (String(data.key || '') !== ACCESS_KEY) return json_({ok:false,error:'Неверный ключ'});
    const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    let sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) sheet = ss.insertSheet(SHEET_NAME);
    if (sheet.getLastRow() === 0) { sheet.appendRow(HEADERS); sheet.setFrozenRows(1); }
    sheet.appendRow([data.date||'',data.game_nickname||'',data.level||'',data.class_name||'',data.teamspeak||'',data.telegram||'',data.added_by||'']);
    return json_({ok:true,test:data.test===true});
  } catch (err) {
    return json_({ok:false,error:String(err)});
  }
}

function json_(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}