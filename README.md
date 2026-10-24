# Recordatorios por Telegram

**Estado: activo desde el 2026-10-23.** Manda los recordatorios de rutina, inglés y
finanzas al Telegram de Engell cada día. Corre en GitHub Actions (nube), no depende
de que la PC esté encendida.

| Cosa | Dónde |
|---|---|
| Repo (público) | https://github.com/Engelllop/recordatorios |
| Runner primario | **Google Apps Script**, cada 5 min de verdad → [`apps-script/GUIA.md`](apps-script/GUIA.md) |
| Workflow | `.github/workflows/recordatorios.yml` — solo manual (cron desactivado el 10/24) |
| Horarios | `schedule.json` ← se edita ahí |
| Lógica | `reminders.py` (GitHub) y `apps-script/Code.gs` (Apps Script) |
| Bot | el mismo bot de Miki: token en `C:\dev\miki\.env` |
| Secretos | `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en el repo + propiedades del script |
| Estado anti-repetidos | `sent_state.json` (GitHub) / propiedades del script (Apps Script) |

```
schedule.json ──► GitHub Actions (cron */5) ──► bot de Telegram ──► celular
                        └─ reminders.py decide y guarda sent_state.json
```

> **El repo es público, así que `schedule.json` NO lleva datos sensibles.** Montos,
**nombres y detalles viven en la bóveda** (`finanzas/vencimientos.md`); acá solo van
días, horas y recordatorios genéricos. Los minutos de Actions de un repo público son
ilimitados, y por eso el cron puede ser cada 5 min en vez de cada 30.

## Qué está programado hoy (25 recordatorios)

**Rutina de ejercicio** (`rutinas/ejercicio.md`, domingo a jueves)

| Día | Hora | Recordatorio |
|---|---|---|
| Dom / Mar / Jue | 05:00 | Fuerza en casa, sesión A o B, 25–35 min |
| Lun / Mié | 05:00 | Caminata rápida 20–30 min |

**Inglés** (`rutinas/ingles.md`, domingo a jueves, 20 min)

| Día | Hora | Bloque |
|---|---|---|
| Dom / Mar | 17:30 | P — shadowing + escucha |
| Lun / Mié | 17:30 | E — escritura + corrección |
| Jue | 17:30 | M — mixto |

**Plata** (`finanzas/vencimientos.md` y `presupuesto/2026-09_plan-ahorro.md`)

| Día | Hora | Qué |
|---|---|---|
| 4 | 08:00 | Cargo fijo de la tarjeta titular (BAC-USD) |
| 6 | 08:00 | Corte Visa BCR → bajar export |
| 7 | 08:00 | Claro postpago |
| 14 | 08:00 | Corte BAC Master → cerrar consumo |
| 15 | 07:30 | Planilla + RAMOS → ahorro · alquiler · SINPE del corte 14 · cuota del préstamo · cobro pendiente |
| 21 | 08:00 | Visa BCR: pago de contado |
| 30 | 08:00 | 2da quincena → barrer excedente al fondo |
| último | 20:00 | Cierre de mes: anotar variable |

**Otros**: revisión semanal de la bóveda (domingo 20:00), pendientes sin registro
(sábado 24/10 09:00), UNED + cierres de diciembre (01/12) y tres cumpleaños
(03/12, 01/01/2027 y 02/10/2027).

## Cómo cambiar un horario

Editá `schedule.json` y hacé push. No hace falta tocar el código.

```json
{
  "id": "fuerza-martes",              // único, sin espacios
  "text": "🏋️ Fuerza en casa…",       // el mensaje que llega
  "type": "weekly",                   // weekly | daily | monthly | once
  "days": ["tue"],                    // solo weekly: sun, mon, tue, …
  "time": "05:00",                    // hora de Costa Rica
  "lead_minutes": 0,                  // avisar X min antes (0 = a la hora)
  "active": true                      // false lo apaga sin borrarlo
}
```

- `monthly` usa `"day": 15` (o `-1` = último día del mes).
- `once` usa `"date": "2026-12-03"`.
- Los `id` no se pueden repetir.
- **No pongas montos ni nombres de personas en `text`**: el repo es público.

## Probar sin esperar

```bash
python reminders.py --dry-run                        # qué enviaría ahora
python reminders.py --dry-run --now 2026-10-25T05:00 # simular un momento
python -m unittest test_reminders                    # 24 tests
```

En GitHub: **Actions → Recordatorios por Telegram → Run workflow → `prueba`**, y
llega un mensaje de confirmación al Telegram.

## Límites y cuidados

- **El cron de GitHub Actions no es confiable: medido 10 corridas en 17 h con `*/5`.**
  Se desactivó el 24/10/2026. El runner real es **Google Apps Script**
  ([`apps-script/GUIA.md`](apps-script/GUIA.md)); el workflow queda solo para pruebas
  manuales (`Run workflow`) y para versionar el código.
- **Ventana de 45 min:** si un trigger se demora, el aviso sale igual y se marca como
  "aviso retrasado". Pasada la ventana se descarta (un aviso de las 05:00 a las 09:00
  no sirve). Para el entreno de las 05:00 la alarma del teléfono sigue despertando; el
  mensaje dice qué toca.
- **El token es del bot de Miki.** No vive en el repo: está en los Secrets de GitHub
  y en `C:\dev\miki\.env`. No commitear `.env` en ningún repo.
- **La bóveda manda.** `finanzas/vencimientos.md` es la fuente de los vencimientos:
  si un pago cambia de fecha, se actualiza ahí y acá. Los recordatorios son estáticos
  (no leen Drive desde Actions).
- Si GitHub desactiva el cron (p. ej. 60 días sin actividad en un repo público), se
  reactiva desde la pestaña Actions o con cualquier commit.
- `sent_state.json` evita avisos repetidos entre corridas; se commitea solo cuando hay
  algo nuevo que enviar.

## Probar local contra el bot real

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."; $env:TELEGRAM_CHAT_ID = "..."
python reminders.py --test
```

*Última actualización: 2026-10-23 — armado por DSH con los datos de la bóveda
(`rutinas/ejercicio.md`, `rutinas/ingles.md`, `finanzas/vencimientos.md`,
`finanzas/presupuesto/2026-09_plan-ahorro.md`, `USER.md`).*
