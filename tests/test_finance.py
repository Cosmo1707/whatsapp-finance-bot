import copy
import importlib
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock, patch

from src.message_handler import MessageHandler, pending_ids
from src.parser import parse_message
from src.sheets_service import GoogleSheetsService, HEADERS, LEDGER
from src.timestamps import timestamp_lima
from src.whatsapp_service import WhatsAppService


class Request:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeAPI:
    """Sheets en memoria: conserva datos aunque la respuesta de escritura falle."""
    def __init__(self):
        self.tables = {
            'Hoja1': [['Fecha', 'Categoría', 'Descripción', 'Monto', 'Tipo', 'Persona', 'Message_ID']],
            'Clientas': [['Fecha', 'Teléfono', 'Mensaje', 'Message_ID']],
            LEDGER: [HEADERS.copy()],
        }
        self.failures = []
        self.writes = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def fail(self, operation, fragment, after=False):
        self.failures.append((operation, fragment, after))

    def execute(self, op, target, fn):
        failure = next((f for f in self.failures if f[0] == op and f[1] in target), None)
        if failure:
            self.failures.remove(failure)
            if not failure[2]:
                raise TimeoutError('Fallo simulado antes de escribir')
        result = fn()
        if failure:
            raise TimeoutError('Respuesta perdida después de escribir')
        return result

    def coordinates(self, target):
        title, cells = target.rsplit('!', 1)
        title = title.strip("'").replace("''", "'")
        match = re.fullmatch(r'([A-Z])(\d*)(?::([A-Z])(\d*))?', cells)
        a, r, b, end = match.groups()
        return title, ord(a) - 65, int(r or 1) - 1, ord(b or a) - 65, int(end or r or len(self.tables[title]))

    def get(self, **kwargs):
        if 'range' not in kwargs:
            return Request(lambda: {'sheets': [
                {'properties': {'title': title, 'index': i}}
                for i, title in enumerate(self.tables)]})
        target = kwargs['range']

        def read():
            title, col, start, last, stop = self.coordinates(target)
            rows = [row[col:last + 1] for row in self.tables[title][start:stop]]
            while rows and not any(v != '' for v in rows[-1]):
                rows.pop()
            return {'values': copy.deepcopy(rows)}
        return Request(lambda: self.execute('get', target, read))

    def update(self, **kwargs):
        target = kwargs['range']

        def write():
            title, col, row, last, _ = self.coordinates(target)
            table = self.tables[title]
            while len(table) <= row:
                table.append([])
            table[row] += [''] * max(0, last + 1 - len(table[row]))
            table[row][col:last + 1] = copy.deepcopy(kwargs['body']['values'][0])
            self.writes.append((target, kwargs['valueInputOption']))
            return {}
        return Request(lambda: self.execute('update', target, write))

    def append(self, **kwargs):
        target = kwargs['range']

        def write():
            title = target.rsplit('!', 1)[0].strip("'")
            values = copy.deepcopy(kwargs['body']['values'][0])
            self.tables[title].append(values)
            row = len(self.tables[title])
            return {'updates': {'updatedRange': f"'{title}'!A{row}:G{row}"}}
        return Request(lambda: self.execute('append', target, write))


class FinanceTests(unittest.TestCase):
    def setUp(self):
        # Toda salida de red está prohibida durante estas pruebas.
        self.network = patch('requests.sessions.Session.request', side_effect=AssertionError('Red prohibida'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.api = FakeAPI()
        self.sheets = GoogleSheetsService.__new__(GoogleSheetsService)
        self.sheets.service = self.api
        self.sheets.spreadsheet_id = 'fake-only'
        self.whatsapp = Mock()
        self.handler = MessageHandler(self.sheets, self.whatsapp)

    def process(self, message_id='wamid.test', phone='51986981127', message='comida menu 12'):
        self.handler.process_message(phone, message, message_id)

    def test_duplicate_once(self):
        self.process()
        self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 2)
        self.whatsapp.send_message.assert_called_once()
        self.assertEqual(self.sheets.get_record('wamid.test')['state'], 'COMPLETADO')

    def test_simultaneous_delivery(self):
        barrier = Barrier(2)
        def delivery(_):
            barrier.wait()
            self.process()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(delivery, range(2)))
        self.assertEqual(len(self.api.tables['Hoja1']), 2)
        self.whatsapp.send_message.assert_called_once()

    def test_lookup_failure_does_not_write(self):
        self.api.fail('get', LEDGER)
        with self.assertRaises(TimeoutError):
            self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 1)
        self.assertEqual(len(self.api.tables[LEDGER]), 1)

    def test_reservation_response_lost(self):
        self.api.fail('append', LEDGER, after=True)
        with self.assertRaises(TimeoutError):
            self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 1)
        self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 2)
        self.assertEqual(len(self.api.tables[LEDGER]), 2)

    def test_write_failure_then_retry(self):
        self.api.fail('update', "'Hoja1'!A2")
        with self.assertRaises(TimeoutError):
            self.process()
        record = self.sheets.get_record('wamid.test')
        self.assertEqual(record['state'], 'ERROR')
        first_date = record['plan']['values'][0]
        self.process()
        self.assertEqual(self.api.tables['Hoja1'][1][0], first_date)
        self.assertEqual(len(self.api.tables['Hoja1']), 2)

    def test_write_succeeded_response_lost_and_restart(self):
        self.api.fail('update', "'Hoja1'!A2", after=True)
        with self.assertRaises(TimeoutError):
            self.process()
        self.handler = MessageHandler(self.sheets, self.whatsapp)
        self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 2)
        target_writes = [x for x in self.api.writes if "'Hoja1'" in x[0]]
        self.assertEqual(len(target_writes), 1)

    def test_completion_write_failed_does_not_repeat_expense(self):
        self.api.fail('update', "!B2:C2")
        with self.assertRaises(TimeoutError):
            self.process()
        self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 2)

    def test_confirmation_failure_does_not_repeat_expense(self):
        self.whatsapp.send_message.side_effect = TimeoutError()
        self.process()
        self.process()
        record = self.sheets.get_record('wamid.test')
        self.assertEqual((record['state'], record['reply_state']), ('COMPLETADO', 'INCIERTA'))
        self.assertEqual(len(self.api.tables['Hoja1']), 2)
        self.whatsapp.send_message.assert_called_once()

    def test_reply_state_response_lost_does_not_resend(self):
        self.api.fail('update', '!G2', after=True)
        with self.assertRaises(TimeoutError):
            self.process()
        self.process()
        self.whatsapp.send_message.assert_not_called()
        self.assertEqual(self.sheets.get_record('wamid.test')['reply_state'], 'ENVIANDO')

    def test_shadia(self):
        self.process(phone='51961906635')
        self.assertEqual(self.api.tables['Hoja1'][1][5:], ['Shadia', 'wamid.test'])

    def test_client_duplicate(self):
        self.process(phone='51000000000', message='=1+1')
        self.process(phone='51000000000', message='=1+1')
        self.assertEqual(len(self.api.tables['Clientas']), 2)
        self.assertEqual(self.api.tables['Clientas'][1][2:], ['=1+1', 'wamid.test'])
        self.assertTrue(all(mode == 'RAW' for _, mode in self.api.writes))

    def test_legacy_not_reprocessed_or_modified(self):
        self.api.tables[LEDGER].append(['wamid.test'])
        before = copy.deepcopy(self.api.tables)
        self.process()
        self.assertEqual(self.api.tables, before)

    def test_missing_id(self):
        with self.assertRaises(ValueError):
            self.process(message_id='')
        self.assertEqual(len(self.api.tables['Hoja1']), 1)

    def test_occupied_reserved_row_never_overwritten(self):
        self.api.fail('update', "'Hoja1'!A2")
        with self.assertRaises(TimeoutError):
            self.process()
        self.api.tables['Hoja1'].append(['dato manual'])
        with self.assertRaises(ValueError):
            self.process()
        self.assertEqual(self.api.tables['Hoja1'][1], ['dato manual'])

    def test_historical_finance_rows_untouched(self):
        historical = ['01/09/2026 12:00', 'Comida', 'menu', 12, 'Egreso', 'Daniel']
        self.api.tables['Hoja1'].append(historical.copy())
        self.process()
        self.assertEqual(self.api.tables['Hoja1'][1], historical)
        self.assertEqual(len(self.api.tables['Hoja1']), 3)

    def test_two_distinct_ids_same_text_are_two_expenses(self):
        self.process('one')
        self.process('two')
        self.assertEqual(len(self.api.tables['Hoja1']), 3)

    def test_wrong_headers_fail_closed(self):
        self.api.tables['Hoja1'][0][-1] = 'Otra cosa'
        with self.assertRaises(ValueError):
            self.process()
        self.assertEqual(len(self.api.tables[LEDGER]), 1)

    def test_pending_recovery_after_no_more_webhook_deliveries(self):
        self.api.fail('update', "'Hoja1'!A2")
        with self.assertRaises(TimeoutError):
            self.process()
        self.assertEqual(pending_ids(self.sheets), ['wamid.test'])
        recovered = MessageHandler(self.sheets, self.whatsapp)
        for mid in pending_ids(self.sheets):
            plan = self.sheets.get_record(mid)['plan']
            recovered.process_message(plan['from_phone'], plan['original'], mid)
        self.assertEqual(pending_ids(self.sheets), [])
        self.assertEqual(len(self.api.tables['Hoja1']), 2)

    def test_duplicate_control_records_fail_closed(self):
        self.process()
        self.api.tables[LEDGER].append(copy.deepcopy(self.api.tables[LEDGER][1]))
        with self.assertRaises(ValueError):
            self.process()
        self.assertEqual(len(self.api.tables['Hoja1']), 2)

    def test_same_id_different_message_rejected(self):
        self.process()
        with self.assertRaises(ValueError):
            self.process(message='comida otra 15')
        self.assertEqual(len(self.api.tables['Hoja1']), 2)

    def test_confirmation_sent_but_status_write_failed(self):
        original = self.sheets.set_reply_state
        def fail_sent(record, state):
            if state == 'ENVIADA':
                raise TimeoutError()
            original(record, state)
        with patch.object(self.sheets, 'set_reply_state', side_effect=fail_sent):
            with self.assertRaises(TimeoutError):
                self.process()
        self.process()
        self.whatsapp.send_message.assert_called_once()
        self.assertEqual(len(self.api.tables['Hoja1']), 2)

    def test_two_concurrent_distinct_messages_have_distinct_rows(self):
        barrier = Barrier(2)
        def delivery(mid):
            barrier.wait()
            self.process(mid)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(delivery, ['one', 'two']))
        self.assertEqual(len(self.api.tables['Hoja1']), 3)
        self.assertNotEqual(self.sheets.get_record('one')['row'], self.sheets.get_record('two')['row'])

    def test_help_only_reply(self):
        self.process(message='/ayuda')
        self.process(message='/ayuda')
        self.assertEqual(len(self.api.tables['Hoja1']), 1)
        self.whatsapp.send_message.assert_called_once()

    def test_webhook_batch_retries_and_bridge_route(self):
        with patch('src.message_handler.MessageHandler', return_value=self.handler):
            module = importlib.import_module('src.app')
        def event(mid, text='comida menu 12'):
            return {'type': 'text', 'id': mid, 'from': '51986981127', 'text': {'body': text}}
        def payload(messages):
            return {'object': 'whatsapp_business_account', 'entry': [
                {'changes': [{'value': {'messages': messages}}]}]}
        with patch.object(module, 'handler', self.handler):
            client = module.app.test_client()
            self.api.fail('update', "'Hoja1'!A2")
            batch = payload([event('one'), event('two')])
            self.assertEqual(client.post('/webhook', json=batch).status_code, 503)
            self.assertEqual(client.post('/webhook', json=batch).status_code, 200)
            self.assertEqual(len(self.api.tables['Hoja1']), 3)
            with patch.object(module, 'reenviar_a_studio28') as bridge:
                result = client.post('/webhook', json=payload([event('studio', 'sí')]))
                self.assertEqual(result.status_code, 200)
                bridge.assert_called_once_with('51986981127', 'sí', 'studio')


class TimestampTests(unittest.TestCase):
    def test_midnight_lima_and_three_digits(self):
        before = datetime(2026, 9, 11, 4, 59, 59, 987654, tzinfo=timezone.utc)
        after = datetime(2026, 9, 11, 5, 0, 0, 1234, tzinfo=timezone.utc)
        self.assertEqual(timestamp_lima(before), '10/09/2026 23:59:59.987')
        self.assertEqual(timestamp_lima(after), '11/09/2026 00:00:00.001')

    def test_parser_uses_central_clock(self):
        with patch('src.parser.timestamp_lima', return_value='10/09/2026 22:41:17.384'):
            data = parse_message('comida menu 12', '51961906635')
        self.assertEqual(data['fecha'], '10/09/2026 22:41:17.384')
        self.assertEqual(data['persona'], 'Shadia')

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            timestamp_lima(datetime(2026, 9, 10))


class WhatsAppTests(unittest.TestCase):
    def test_http_error_propagates_and_timeout_is_set(self):
        response = Mock()
        response.raise_for_status.side_effect = RuntimeError('HTTP error simulado')
        with patch('src.whatsapp_service.requests.post', return_value=response) as post:
            with self.assertRaises(RuntimeError):
                WhatsAppService().send_message('fake', 'fake')
        self.assertEqual(post.call_args.kwargs['timeout'], (5, 20))


if __name__ == '__main__':
    unittest.main()
