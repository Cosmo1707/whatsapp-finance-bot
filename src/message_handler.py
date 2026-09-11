import logging
from threading import RLock

from src.parser import PERSONAS, parse_message
from src.sheets_service import GoogleSheetsService
from src.timestamps import timestamp_lima
from src.whatsapp_service import WhatsAppService

NUMEROS_AUTORIZADOS = list(PERSONAS)
# También serializa el cliente httplib2 compartido. Requiere UN proceso/instancia.
PROCESSING_LOCK = RLock()
logger = logging.getLogger(__name__)


class MessageHandler:
    def __init__(self, sheets=None, whatsapp=None):
        self.whatsapp = whatsapp if whatsapp is not None else WhatsAppService()
        self.sheets = sheets if sheets is not None else GoogleSheetsService()

    def prepare_message(self, from_phone, message):
        message = message.strip()
        if from_phone not in NUMEROS_AUTORIZADOS:
            return {
                "kind": "client", "values": [timestamp_lima(), from_phone, message],
                "reply": "Hola 👋 Este número ya no tiene atención por WhatsApp.\n"
                         "Para cualquier consulta, escríbeme a mi número personal:\n"
                         "📱 +51 924 400 897 (Leslye)\n¡Gracias!",
            }
        if message.lower() == '/ayuda':
            return {"kind": "reply", "values": [], "reply": (
                "📋 *FinanceTracker*\n\nEnvía tus gastos así:\n"
                "`Categoria descripcion monto`\n\nEjemplos:\n"
                "• antojo chocolate 5.40\n• comida menu 12\n"
                "• salario agosto 5000\n• perros croquetas 200"
            )}
        data = parse_message(message, from_phone)
        if not data:
            return {"kind": "reply", "values": [], "reply": (
                "🤔 No entendí. Usa: `Categoria descripcion monto`\n"
                "Ej: `comida menu 12`\n\nEscribe /ayuda para más info"
            )}
        return {
            "kind": "expense",
            "values": [data[key] for key in
                       ('fecha', 'categoria', 'descripcion', 'monto', 'tipo', 'persona')],
            "reply": (f"✅ {data['tipo']} registrado:\n"
                      f"📌 {data['categoria']}: {data['descripcion']}\n"
                      f"💰 S/ {data['monto']:.2f}\n📅 {data['fecha']}"),
        }

    def process_message(self, from_phone, message, message_id):
        if not message_id or not from_phone:
            raise ValueError("El mensaje requiere ID y remitente")
        with PROCESSING_LOCK:
            record = self.sheets.get_record(message_id)
            if record and record['state'] == 'LEGACY':
                logger.warning("ID histórico sin resultado verificable: %s", message_id)
                return
            if record is None:
                plan = self.prepare_message(from_phone, message)
                plan.update(from_phone=from_phone, original=message)
                record = self.sheets.reserve(message_id, plan)
            elif (record['plan']['from_phone'] != from_phone or
                  record['plan']['original'] != message):
                raise ValueError("ID existente con otro contenido; requiere revisión")

            if record['state'] != 'COMPLETADO':
                try:
                    self.sheets.write_reserved(record)
                    self.sheets.set_state(record, 'COMPLETADO')
                except Exception:
                    # ERROR conserva reserva y datos: no significa que Google no escribió.
                    try:
                        self.sheets.set_state(record, 'ERROR')
                    except Exception:
                        logger.warning("No se pudo actualizar el estado de %s", message_id)
                    raise

            if record['reply_state'] != 'PENDIENTE':
                # ENVIANDO puede indicar envío exitoso cuya respuesta se perdió.
                return
            self.sheets.set_reply_state(record, 'ENVIANDO')
            try:
                self.whatsapp.send_message(from_phone, record['plan']['reply'])
            except Exception:
                logger.warning("Confirmación incierta para %s; gasto no se repite", message_id)
                self.sheets.set_reply_state(record, 'INCIERTA')
                return
            self.sheets.set_reply_state(record, 'ENVIADA')


def pending_ids(sheets):
    return [row[0] for row in sheets.ledger_rows()[1:]
            if len(row) == 7 and (row[1] in ('PROCESANDO', 'ERROR') or
                                  (row[1] == 'COMPLETADO' and row[6] == 'PENDIENTE'))]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Recuperación manual; detener antes el servidor web.')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--list-pending', action='store_true')
    action.add_argument('--recover-pending', action='store_true')
    args = parser.parse_args()
    handler = MessageHandler()
    failed = False
    for message_id in pending_ids(handler.sheets):
        print(message_id)
        if args.recover_pending:
            try:
                record = handler.sheets.get_record(message_id)
                plan = record['plan']
                handler.process_message(plan['from_phone'], plan['original'], message_id)
            except Exception:
                logger.exception('No se pudo recuperar %s', message_id)
                failed = True
    raise SystemExit(1 if failed else 0)
