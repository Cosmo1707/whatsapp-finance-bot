import json
import os
import re
import unicodedata
import google_auth_httplib2
import httplib2

from config.settings import Config
from google.oauth2 import service_account
from googleapiclient.discovery import build
from src.timestamps import timestamp_lima

LEDGER = "Mensajes Procesados"
HEADERS = ["Message_ID", "Estado", "Timestamp", "Destino", "Fila", "Datos_JSON", "Confirmacion"]


def quoted(title):
    return "'" + title.replace("'", "''") + "'"


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.strip().lower())
                   if unicodedata.category(c) != "Mn")


class GoogleSheetsService:
    def __init__(self):
        self.spreadsheet_id = Config.SPREADSHEET_ID
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.credentials_path = os.path.join(project_dir, "google-credentials.json")
        self.service = self._authenticate()

    def _authenticate(self):
        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_path,
            scopes=['https://www.googleapis.com/auth/spreadsheets'])
        http = google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=20))
        return build('sheets', 'v4', http=http)

    def read(self, target):
        return self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id, range=target,
            valueRenderOption='UNFORMATTED_VALUE').execute().get('values', [])

    def update(self, target, values):
        return self.service.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id, range=target,
            valueInputOption='RAW', body={'values': [values]}).execute()

    def ledger_rows(self):
        rows = self.read(f"{quoted(LEDGER)}!A:G")
        if not rows or rows[0] != HEADERS:
            raise ValueError("Preparar encabezados A:G de Mensajes Procesados según OPERACION.md")
        return rows

    def get_record(self, message_id):
        matches = [(i, row) for i, row in enumerate(self.ledger_rows(), 1)
                   if row and row[0] == message_id]
        if not matches:
            return None
        # Los IDs históricos se conservan, sin asumir que su efecto se completó.
        if all(not any(row[1:]) for _, row in matches):
            return {'state': 'LEGACY'}
        if len(matches) != 1:
            raise ValueError("ID repetido en control; requiere reconciliación manual")
        index, row = matches[0]
        if len(row) != 7 or row[1] not in ('PROCESANDO', 'ERROR', 'COMPLETADO'):
            raise ValueError("Registro de control incompleto o estado desconocido")
        plan = json.loads(row[5])
        return dict(id=message_id, index=index, state=row[1], destination=row[3],
                    row=int(row[4]), plan=plan, reply_state=row[6])

    def destination(self, kind):
        if kind == 'reply':
            return ''
        if kind == 'client':
            title, expected = 'Clientas', ['fecha', 'telefono', 'mensaje', 'message_id']
        else:
            sheets = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                fields='sheets.properties').execute()['sheets']
            # A:F sin nombre utilizaba la primera pestaña; ahora se valida y se nombra.
            title = min(sheets, key=lambda s: s['properties']['index'])['properties']['title']
            expected = ['fecha', 'categoria', 'descripcion', 'monto', 'tipo', 'persona', 'message_id']
        end = 'D' if kind == 'client' else 'G'
        headers = self.read(f"{quoted(title)}!A1:{end}1")
        if not headers or [normalized(str(v)) for v in headers[0]] != expected:
            raise ValueError("Encabezados de destino incorrectos; ver OPERACION.md")
        return title

    def reserve(self, message_id, plan):
        destination = self.destination(plan['kind'])
        target_row = 0
        if destination:
            end = 'G' if plan['kind'] == 'expense' else 'D'
            occupied = len(self.read(f"{quoted(destination)}!A:{end}"))
            reservations = [int(row[4]) for row in self.ledger_rows()[1:]
                            if len(row) >= 5 and row[3] == destination and row[4]]
            target_row = max([1, occupied] + reservations) + 1
        # Datos inmutables: un reinicio reutiliza la fecha, respuesta y fila originales.
        payload = json.dumps(plan, ensure_ascii=False, allow_nan=False)
        if len(payload) > 45000:
            raise ValueError("Mensaje demasiado grande para la celda de recuperación")
        values = [message_id, 'PROCESANDO', timestamp_lima(), destination,
                  target_row, payload, 'PENDIENTE']
        # No hay efecto externo hasta recibir confirmación de esta reserva.
        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"{quoted(LEDGER)}!A:G",
            valueInputOption='RAW', insertDataOption='INSERT_ROWS',
            body={'values': [values]}).execute()
        match = re.search(r'!A(\d+):G\d+$', result['updates']['updatedRange'])
        if not match:
            raise ValueError("No se pudo identificar la fila de control")
        return dict(id=message_id, index=int(match.group(1)), state='PROCESANDO',
                    destination=destination, row=target_row, plan=plan,
                    reply_state='PENDIENTE')

    def write_reserved(self, record):
        plan = record['plan']
        if plan['kind'] == 'reply':
            return
        title = self.destination(plan['kind'])
        if title != record['destination']:
            raise ValueError("Cambió la pestaña de destino; revisar antes de continuar")
        end = 'G' if plan['kind'] == 'expense' else 'D'
        rows = self.read(f"{quoted(title)}!A:{end}")
        expected = plan['values'] + [record['id']]
        matches = [(i, row) for i, row in enumerate(rows, 1)
                   if len(row) == len(expected) and row[-1] == record['id']]
        if matches:
            if len(matches) != 1 or matches[0] != (record['row'], expected):
                raise ValueError("Fila movida, modificada o ID duplicado; revisar")
            return
        row_number = record['row']
        current = rows[row_number - 1] if row_number <= len(rows) else []
        if any(value != '' for value in current):
            raise ValueError("La fila reservada está ocupada; no se sobrescribe")
        # Mismo rango y mismos valores incluso después de un timeout o reinicio.
        self.update(f"{quoted(title)}!A{row_number}:{end}{row_number}", expected)

    def set_state(self, record, state):
        self.update(f"{quoted(LEDGER)}!B{record['index']}:C{record['index']}",
                    [state, timestamp_lima()])
        record['state'] = state

    def set_reply_state(self, record, state):
        self.update(f"{quoted(LEDGER)}!G{record['index']}", [state])
        record['reply_state'] = state
