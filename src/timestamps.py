"""Timestamps de procesamiento en Perú, con precisión visible de milisegundos."""
from datetime import datetime
from zoneinfo import ZoneInfo

LIMA = ZoneInfo("America/Lima")


def timestamp_lima(instant=None):
    instant = instant or datetime.now(LIMA)
    if instant.tzinfo is None:
        raise ValueError("Se requiere un datetime con zona horaria")
    return instant.astimezone(LIMA).strftime("%d/%m/%Y %H:%M:%S.%f")[:-3]
