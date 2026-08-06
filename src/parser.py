from datetime import datetime

def parse_message(message):
    """
    Parsea mensajes como:
    "antojo chocolate 5.40"
    "salario agosto 5000"
    
    Retorna: (categoria, descripcion, monto) o None si no entiende
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
    
    # Lo del medio es la descripción (puede estar vacío)
    if len(parts) > 2:
        descripcion = " ".join(parts[1:-1])
    else:
        descripcion = categoria
    
    # Fecha automática
    fecha = datetime.now().strftime('%d/%m/%Y %H:%M')
    
    # Determinar tipo
    categorias_ingreso = ["salario", "sueldo", "cobro", "venta", "ingreso"]
    if categoria.lower() in categorias_ingreso:
        tipo = "Ingreso"
    else:
        tipo = "Egreso"
    
    return {
        'fecha': fecha,
        'categoria': categoria,
        'descripcion': descripcion,
        'monto': monto,
        'tipo': tipo
    }
