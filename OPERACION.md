# Corrección de duplicados y timestamps

Implementada sobre 6bd42ebd604fab56d31d3bb2940d953b2fcc655c. No migra ni limpia datos históricos. Las pruebas usan memoria y no acceden a Google Sheets ni WhatsApp reales.

## Antes de desplegar

1. Detener el bot anterior y esperar a que terminen sus solicitudes. No ejecutar simultáneamente versiones viejas/nuevas, otros escritores automáticos ni varias instancias.
2. Guardar una copia de seguridad de la hoja. Mantener nombres, orden de pestañas y columnas existentes.
3. En la pestaña financiera actual (la primera pestaña del archivo), conservar A-F y añadir en **G1**: `Message_ID`. Los encabezados A-F deben ser Fecha, Categoría, Descripción, Monto, Tipo, Persona (se toleran mayúsculas y acentos). No sobrescribir G si ya contiene información: resolver esa incompatibilidad antes de activar el bot.
4. En `Clientas`, conservar A-C y añadir **D1**: `Message_ID`. Los encabezados A-C deben ser Fecha, Teléfono, Mensaje. Si D ya tiene información, no sobrescribirla.
5. En `Mensajes Procesados`, preparar A1:G1 exactamente:

   `Message_ID | Estado | Timestamp | Destino | Fila | Datos_JSON | Confirmacion`

   Si A1 es un ID real y no un encabezado, insertar una fila al principio **antes de arrancar la nueva versión**, conservando todos los IDs. Si B-G ya contienen información, no reemplazarla. Los IDs históricos de A siguen intactos, con B-G vacíos.
6. Mantener suficiente cantidad de filas vacías disponibles en las pestañas de destino. Si se alcanza el final de la cuadrícula, añadir filas **al final** y recuperar pendientes. El código no borra ni inserta filas históricas.
7. Desde este momento, no insertar, eliminar, ordenar físicamente ni mover filas de las tres pestañas. Usar vistas de filtro para consultar. Es recomendable proteger la estructura contra cambios accidentales y evitar ediciones manuales en filas del bot. No cambiar la primera pestaña.
8. Desplegar el código con las dependencias actualizadas. **Un proceso y una instancia**. El arranque existente `python src/app.py` se conserva, ahora sin debug/reloader y con el puerto `PORT` si Render lo proporciona. Si ya se usa Gunicorn, configurar `--workers 1` y no activar reload; no es una dependencia añadida por este cambio. Evitar despliegues solapados: detener completamente la versión anterior antes de activar la nueva.

Antes de desplegar esta rama, configurar la variable de entorno `STUDIO28_TOKEN` con el mismo valor que actualmente acepta Studio 28. No se rota el token; solo cambia su origen. Sin esta variable, el puente no puede autenticarse. Se conserva la ruta de credenciales actualmente utilizada en la raíz. `tzdata` es la nueva dependencia necesaria para disponer de America/Lima también en sistemas sin base IANA instalada. requirements.txt y .gitignore se normalizaron de UTF-16 a UTF-8.

## Flujo de finanzas y Clientas

1. Exigir `message_id` y remitente. Tomar un bloqueo global dentro del proceso, también para usar el cliente Google compartido.
2. Consultar `Mensajes Procesados`. Un fallo de consulta detiene el procesamiento y produce HTTP 503; nunca se interpreta como ID nuevo.
3. Para un ID nuevo, preparar los datos y la respuesta, elegir una fila libre considerando las reservas anteriores y persistir `PROCESANDO`, destino, fila y datos JSON. No escribir el gasto hasta que Google confirme la reserva.
4. Escribir A:G en finanzas o A:D en Clientas mediante actualización de la fila reservada, incluyendo ID. Se usan valores RAW: los textos y milisegundos se conservan literalmente; el monto sigue siendo numérico. Las fechas nuevas son texto visible, lo que debe tenerse en cuenta en fórmulas que antes esperaban una fecha numérica.
5. Si Google ya guardó la misma fila con el mismo ID y contenido, reconocerla sin añadir otra. Si la fila está ocupada por algo distinto, movida o duplicada, detenerse para revisión; no sobrescribirla.
6. Marcar `COMPLETADO` solamente después de confirmar o reconciliar la escritura financiera. Un fallo conserva reserva/datos y, si es posible, marca `ERROR`. ERROR no significa que Google no haya escrito: un timeout puede ocultar una escritura exitosa.
7. La confirmación tiene estado separado: PENDIENTE → ENVIANDO → ENVIADA. Un fallo de envío queda INCIERTA. No se vuelve a guardar un gasto para repetir una confirmación.

La reserva guarda la fecha y el contenido original: un reinicio o reintento usa esos mismos datos. Para /ayuda o mensajes no interpretables no hay fila financiera; COMPLETADO indica que se preparó la respuesta, cuyo resultado se controla por separado.

Los IDs históricos con solo A se reconocen como LEGACY y no se reproducen ni se convierten falsamente en COMPLETADO. El esquema viejo no permite saber si su gasto se guardó. Requieren una reconciliación histórica futura, fuera de esta modificación.

## Timestamps y personas

`src/timestamps.py` centraliza `ZoneInfo("America/Lima")` y produce `dd/mm/aaaa HH:MM:SS.mmm`, por ejemplo `10/09/2026 22:41:17.384`. Son tres dígitos obtenidos de la precisión real del reloj de procesamiento, truncando microsegundos; no se inventan milisegundos a partir del timestamp de Meta, que no se usa para esta fecha. No son necesariamente únicos y no sustituyen al message_id.

Se aplica a finanzas, Clientas y los cambios de estado de Mensajes Procesados. El mapa único identifica Daniel, Leslye y Shadia; también alimenta la lista de autorizados.

## Recuperación manual de pendientes

Los errores de registro provocan 503 para permitir reentregas de Meta. La reserva permanece en Sheets si la reentrega no llega; no hay un trabajador automático ni promesa de reintentos ilimitados de Meta.

Con credenciales configuradas y **el servidor web y cualquier otro escritor detenidos**, desde la raíz del repositorio:

```console
python -m src.message_handler --list-pending
python -m src.message_handler --recover-pending
```

El primer comando solo lista IDs. El segundo escribe registros pendientes y puede enviar sus confirmaciones reales: no es una prueba ni una limpieza. Reutiliza las reservas existentes. No procesa IDs antiguos ni confirmaciones ENVIANDO/INCIERTA. Esas confirmaciones requieren comprobar manualmente si llegaron; no cambiar su estado a PENDIENTE a ciegas. Ante un conflicto de filas, no borrar la reserva ni el ID: revisar la fila señalada y los datos guardados antes de corregir.

## Limitaciones residuales

- Sheets no ofrece compare-and-swap ni unicidad transaccional. El bloqueo solo cubre hilos del mismo proceso. Dos procesos/instancias o editores externos pueden competir por la misma fila. Esta versión **no garantiza exactamente una vez** en esas condiciones, incluso si se buscan IDs antes de escribir.
- Las filas reservadas deben conservar su posición. El control comprueba conflictos visibles, pero no puede impedir una edición externa entre su lectura y escritura.
- Una escritura incierta de la reserva podría acabar produciendo varias entradas de control si llega tardíamente. Si se detecta más de una entrada del mismo ID, se detiene para revisión en lugar de elegir y reproducir una arbitrariamente. Puede quedar una fila sin utilizar; no se limpia automáticamente.
- ENVIANDO puede quedar tras una caída antes o después del envío. Evitar reenvíos automáticos en ese estado puede dejar una confirmación pendiente de revisión, pero no pierde ni duplica el gasto completado.
- Los datos de recuperación incluyen texto, remitente y respuesta dentro de la hoja compartida. Mantener sus permisos limitados a quienes ya deben acceder a esos datos.
- Las búsquedas siguen leyendo columnas/rangos completos y consumen cuota; esta solución es para el volumen actual de un bot personal.
- Studio 28 conserva exactamente el ruteo, token, payload y anti-duplicado antiguo de su rama; por pedido explícito no se corrigen aquí sus ventanas de pérdida ni sus errores de envío. Sus nuevas entradas siguen usando solo la columna A. Tampoco se añade en esta entrega la validación de firma del webhook: la seguridad de entrada sigue siendo un pendiente separado.

## Validación y prueba real posterior

Pruebas locales sin credenciales:

```console
python -B -m unittest discover -s tests -v
```

Después de preparar las columnas y desplegar:

1. Enviar una sola vez un gasto real pequeño desde un autorizado, por ejemplo `comida menu 12` si corresponde a un gasto real. No enviar de nuevo solo porque tarde la confirmación.
2. Verificar una fila con A-F conservadas, fecha de Perú con segundos y tres decimales, y G con un ID no vacío.
3. Buscar ese mismo ID en Mensajes Procesados: debe tener COMPLETADO, destino/fila, JSON y confirmación ENVIADA (o INCIERTA si hubo un fallo que requiere revisión).
4. Esperar y comprobar que no apareció otra fila con ese mismo ID. No reenviar manualmente el texto para probar duplicados: WhatsApp asigna un ID nuevo y eso representa otro registro legítimo.
5. En el siguiente gasto real de Shadia, comprobar Persona = Shadia. Su número autorizado sigue siendo el mismo.
6. La repetición artificial de un mismo webhook se verifica con las pruebas aisladas, no contra producción. Si hay ERROR/PROCESANDO persistente, seguir el procedimiento de recuperación anterior.

Para revertir, detener el proceso nuevo y conservar todas las columnas, reservas y datos. Volver al código antiguo reintroduce sus fallos y no recupera pendientes nuevos; preferir pausar y corregir la versión nueva. No ejecutar ambos procesadores a la vez.
