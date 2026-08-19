from datetime import datetime, timedelta, timezone

def parse_message(message, from_phone=None):
    """
    Parsea mensajes como:
    "antojo chocolate 5.40"
    "salario agosto 5000"
    
    Retorna: dict con los datos o None si no entiende
    """
    parts = message.strip().split()
    
    if len(parts) < 2:
        return None
    
    # Última parte es el monto
    try:
        monto = float(parts[-1])
    except ValueError:
        return None
    
    # Primera parte es la categoría
    categoria = parts[0].lower().capitalize()
    
    # Lo del medio es la descripción
    if len(parts) > 2:
        descripcion = " ".join(parts[1:-1])
    else:
        descripcion = categoria
    
    # Fecha automática en hora peruana (UTC-5)
    fecha = datetime.now(timezone.utc) - timedelta(hours=5)
    fecha = fecha.strftime('%d/%m/%Y %H:%M')
    
    # Determinar tipo
    categorias_ingreso = ["salario", "sueldo", "cobro", "venta", "ingreso"]
    if categoria.lower() in categorias_ingreso:
        tipo = "Ingreso"
    else:
        tipo = "Egreso"
    
    # Determinar persona
    if from_phone == "51986981127":
        persona = "Daniel"
    elif from_phone == "51924400897":
        persona = "Leslye"
    else:
        persona = "Desconocido"
    
    return {
        'fecha': fecha,
        'categoria': categoria,
        'descripcion': descripcion,
        'monto': monto,
        'tipo': tipo,
        'persona': persona
    }
