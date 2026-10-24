/**
 * Recordatorios por Telegram — runner en Google Apps Script.
 *
 * Por qué existe: el cron de GitHub Actions se ejecuta muchísimo menos de lo
 * declarado (~10 veces en 17 h con `*​/5`). Apps Script sí dispara cada 5 min.
 *
 * Configuración (una sola vez):
 *   1. script.google.com → Nuevo proyecto → pegar este archivo.
 *   2. ⚙ Configuración del proyecto → Propiedades de la secuencia de comandos:
 *        TELEGRAM_TOKEN   = token del bot
 *        TELEGRAM_CHAT_ID = tu chat id
 *   3. Ejecutar `setup`  → autoriza permisos y crea el trigger de 5 minutos.
 *   4. Ejecutar `probar` → debe llegar un mensaje de prueba al Telegram.
 *
 * El horario se lee de schedule.json del repo público, así que se sigue editando
 * ahí y este runner lo toma en la corrida siguiente.
 */

const SCHEDULE_URL = 'https://raw.githubusercontent.com/Engelllop/recordatorios/master/schedule.json';
const TZ = 'America/Costa_Rica';
const WINDOW_MIN = 45;      // minutos de tolerancia si un trigger se demora
const STATE_KEY = 'sent_state';
const STATE_DAYS = 10;      // cuánto se recuerda lo enviado (Properties tiene 9 KB por valor)

const WD = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
const WD_ES = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];
const MO_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

/** Ejecutar UNA vez: crea el trigger de cada 5 minutos. */
function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) { ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('enviar').timeBased().everyMinutes(5).create();
  Logger.log('OK: trigger cada 5 minutos creado.');
}

/** Prueba manual de conexión con el bot. */
function probar() {
  enviarTelegram_('🔔 Prueba de conexión desde Google Apps Script: el runner está funcionando.');
  Logger.log('Mensaje de prueba enviado.');
}

function pad(n) { return (n < 10 ? '0' : '') + n; }

/** Partes de la fecha local (Costa Rica) a partir de un epoch ms. */
function localParts(ms) {
  var s = Utilities.formatDate(new Date(ms), TZ, 'yyyy-MM-dd HH:mm');
  var d = s.substring(0, 10).split('-').map(Number);
  var h = s.substring(11).split(':').map(Number);
  return {
    y: d[0], m: d[1], d: d[2], hh: h[0], mm: h[1],
    wd: new Date(Date.UTC(d[0], d[1] - 1, d[2])).getUTCDay()
  };
}

function pseudoMs(p) {
  return Date.UTC(p.y, p.m - 1, p.d, p.hh || 0, p.mm || 0);
}

/** Momentos de ese día en que toca el recordatorio (0 o 1). */
function occurrences(rem, p) {
  var hm = String(rem.time).split(':').map(Number);
  var out = [];
  var tipo = rem.type || 'weekly';
  if (tipo === 'once') {
    if (rem.date === p.y + '-' + pad(p.m) + '-' + pad(p.d)) {
      out.push(Date.UTC(p.y, p.m - 1, p.d, hm[0], hm[1]));
    }
  } else if (tipo === 'daily') {
    out.push(Date.UTC(p.y, p.m - 1, p.d, hm[0], hm[1]));
  } else if (tipo === 'weekly') {
    if ((rem.days || []).some(function (k) { return WD[k] === p.wd; })) {
      out.push(Date.UTC(p.y, p.m - 1, p.d, hm[0], hm[1]));
    }
  } else if (tipo === 'monthly') {
    var ultimo = new Date(Date.UTC(p.y, p.m, 0)).getUTCDate();
    var objetivo = rem.day === -1 ? ultimo : rem.day;
    if (p.d === objetivo) out.push(Date.UTC(p.y, p.m - 1, p.d, hm[0], hm[1]));
  }
  return out;
}

function formatWhen(ms) {
  var p = localParts(ms);
  return WD_ES[p.wd] + ' ' + pad(p.d) + ' ' + MO_ES[p.m - 1] + ' ' + pad(p.hh) + ':' + pad(p.mm);
}

function cargarEstado_() {
  try {
    var raw = PropertiesService.getScriptProperties().getProperty(STATE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (e) {
    return {};
  }
}

function guardarEstado_(estado) {
  var cutoff = Date.now() - STATE_DAYS * 86400000;
  var limpio = {};
  Object.keys(estado).forEach(function (k) {
    if (estado[k] >= cutoff) limpio[k] = estado[k];
  });
  PropertiesService.getScriptProperties().setProperty(STATE_KEY, JSON.stringify(limpio));
}

function enviarTelegram_(texto) {
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('TELEGRAM_TOKEN');
  var chat = props.getProperty('TELEGRAM_CHAT_ID');
  if (!token || !chat) {
    throw new Error('Faltan TELEGRAM_TOKEN / TELEGRAM_CHAT_ID en las Propiedades del script.');
  }
  var resp = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
    method: 'post',
    payload: { chat_id: chat, text: texto, disable_web_page_preview: 'true' },
    muteHttpExceptions: true
  });
  var code = resp.getResponseCode();
  if (code < 200 || code >= 300) {
    throw new Error('Telegram HTTP ' + code + ': ' + resp.getContentText().substring(0, 200));
  }
}

/** La función que corre el trigger. */
function enviar() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(30000)) return;
  try {
    var resp = UrlFetchApp.fetch(SCHEDULE_URL + '?t=' + Date.now(), { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) {
      Logger.log('No pude leer schedule.json: HTTP ' + resp.getResponseCode());
      return;
    }
    var schedule = JSON.parse(resp.getContentText());

    var ahoraP = localParts(Date.now());
    var ahora = pseudoMs(ahoraP);
    var ayerP = localParts(ahora - 86400000);

    var estado = cargarEstado_();
    var pendientes = [];

    (schedule.reminders || []).forEach(function (rem) {
      if (rem.active === false) return;
      [ayerP, ahoraP].forEach(function (p) {
        occurrences(rem, p).forEach(function (occ) {
          var lead = (rem.lead_minutes || 0) * 60000;
          var due = occ - lead;
          if (lead > 0 && ahora > occ) return;           // aviso previo ya no sirve
          if (ahora < due || ahora > due + WINDOW_MIN * 60000) return;
          var key = rem.id + '|' + occ;
          if (estado[key]) return;
          pendientes.push({ key: key, rem: rem, occ: occ, due: due });
        });
      });
    });

    pendientes.sort(function (a, b) { return a.due - b.due; });
    if (!pendientes.length) {
      Logger.log('Sin recordatorios pendientes');
      return;
    }

    pendientes.forEach(function (item) {
      var texto = '⏰ ' + item.rem.text + '\n🗓️ ' + formatWhen(item.occ);
      if (ahora - item.due > 10 * 60000) {
        texto += '\n⚠️ Aviso retrasado unos ' + Math.round((ahora - item.due) / 60000) + ' min';
      }
      try {
        enviarTelegram_(texto);
        estado[item.key] = Date.now();
        Logger.log('Enviado: ' + item.rem.id);
      } catch (e) {
        Logger.log('ERROR enviando ' + item.rem.id + ': ' + e);
      }
    });

    guardarEstado_(estado);
  } finally {
    lock.releaseLock();
  }
}
