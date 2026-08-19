import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.settings import Config
from google.oauth2 import service_account
from googleapiclient.discovery import build

class GoogleSheetsService:
    def __init__(self):
        self.spreadsheet_id = Config.SPREADSHEET_ID
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(current_dir)
        self.credentials_path = os.path.join(project_dir, "google-credentials.json")
        
        self.service = self._authenticate()
    
    def _authenticate(self):
        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_path,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        return build('sheets', 'v4', credentials=credentials)
    
    def append_expense(self, fecha, categoria, descripcion, monto, tipo, persona):
        values = [[fecha, categoria, descripcion, monto, tipo, persona]]
        body = {'values': values}
        
        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range='A:F',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        return True

    def append_client(self, phone, message):
        """Guarda el número de una clienta antigua en la hoja Clientas"""
        from datetime import datetime, timedelta, timezone
        fecha = datetime.now(timezone.utc) - timedelta(hours=5)
        fecha = fecha.strftime('%d/%m/%Y %H:%M')
        values = [[fecha, phone, message]]
        body = {'values': values}
        
        self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range='Clientas!A:C',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
