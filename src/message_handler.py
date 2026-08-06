import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import parse_message
from src.sheets_service import GoogleSheetsService
from src.whatsapp_service import WhatsAppService

class MessageHandler:
    def __init__(self):
        self.whatsapp = WhatsAppService()
        self.sheets = GoogleSheetsService()
    
    def process_message(self, from_phone, message):
        message = message.strip()
        
        # Comandos especiales
        if message.lower() == '/ayuda':
            help_text = (
                "📋 *FinanceTracker*\n\n"
                "Envía tus gastos así:\n"
                "`Categoria descripcion monto`\n\n"
                "Ejemplos:\n"
                "• antojo chocolate 5.40\n"
                "• comida menu 12\n"
                "• salario agosto 5000\n"
                "• perros croquetas 200"
            )
            self.whatsapp.send_message(from_phone, help_text)
            return
        
        # Intentar parsear
        data = parse_message(message)
        
        if data:
            # Guardar en Sheets
            self.sheets.append_expense(
                data['fecha'],
                data['categoria'],
                data['descripcion'],
                data['monto'],
                data['tipo']
            )
            # Confirmar
            confirmacion = (
                f"✅ {data['tipo']} registrado:\n"
                f"📌 {data['categoria']}: {data['descripcion']}\n"
                f"💰 S/ {data['monto']:.2f}\n"
                f"📅 {data['fecha']}"
            )
            self.whatsapp.send_message(from_phone, confirmacion)
        else:
            self.whatsapp.send_message(
                from_phone,
                "🤔 No entendí. Usa: `Categoria descripcion monto`\n"
                "Ej: `comida menu 12`\n\n"
                "Escribe /ayuda para más info"
            )
