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
    
    def append_expense(self, fecha, categoria, descripcion, monto, tipo):
        values = [[fecha, categoria, descripcion, monto, tipo]]
        body = {'values': values}
        
        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range='!A:E',
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        return True
