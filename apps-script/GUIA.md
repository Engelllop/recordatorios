# Runner en Google Apps Script (5 minutos, una sola vez)

**Por qué:** el cron de GitHub Actions se ejecuta muchísimo menos de lo declarado
(medido: 10 corridas en 17 h con `*/5`). Apps Script dispara cada 5 minutos de verdad,
es gratis con la cuenta de Google que ya tenés y no necesita PC encendida.

El runner lee `schedule.json` de este repo (público), calcula qué toca y manda el
mensaje por el bot. Los enviados se guardan en las propiedades del script.

## Pasos

1. Abrí <https://script.google.com> → **Nuevo proyecto**.
2. Borrá el contenido de `Code.gs` y pegá el de [`Code.gs`](Code.gs) (este mismo repo).
3. Arriba a la derecha, ⚙ **Configuración del proyecto** → **Propiedades de la
   secuencia de comandos** → **Agregar propiedad**. Dos filas:

   | Propiedad | Valor |
   |---|---|
   | `TELEGRAM_TOKEN` | el token del bot (línea `TELEGRAM_BOT_TOKEN` de `C:\dev\miki\.env`) |
   | `TELEGRAM_CHAT_ID` | el chat id (línea `TELEGRAM_CHAT_ID` de `C:\dev\miki\.env`) |

4. En el editor, elegí la función **`setup`** y **Ejecutar** → autorizá los permisos
   (acceso a internet y triggers). Eso crea el trigger cada 5 minutos.
5. Elegí **`probar`** y **Ejecutar** → tiene que llegar "🔔 Prueba de conexión…" al
   Telegram.
6. Listo. En ⏱ **Ejecuciones** vas a ver una corrida cada 5 minutos.

## Cómo verificar que anda

- En **Ejecuciones**, cada corrida dice `Sin recordatorios pendientes` o
  `Enviado: <id>`.
- Primeros avisos reales: pagos el día 4/6/7/14/15/21/30 a las 07:30–08:00; entreno
  05:00 dom/mar/jue (caminata lun/mié); inglés 17:30 dom–jue; revisión de la bóveda
  domingo 20:00.
- Si una corrida falla, el mensaje queda pendiente y se reintenta en la siguiente
  dentro de la ventana de 45 min.

## Notas

- **Cuota:** Apps Script gratis da 90 min/día de runtime de triggers; acá se usan ~15
  min/día. Sobra.
- **Horario:** se edita `schedule.json` en el repo; la corrida siguiente lo toma (se
  pide con cache-buster).
- **Estado:** propiedades del script, retención 10 días (límite de 9 KB por valor).
- **GitHub Actions** queda como respaldo/manual (`workflow_dispatch`). Cuando
  confirmes que Apps Script corre bien, se le puede quitar el `schedule` para no
  duplicar avisos.
