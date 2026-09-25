function doGet() {
  return ContentService.createTextOutput(JSON.stringify({ok:true, service:'Instinct Google Sheets'})).setMimeType(ContentService.MimeType.JSON);
}
