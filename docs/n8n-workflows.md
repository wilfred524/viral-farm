# Propuesta de workflows de n8n

> Principio rector (ver `decisiones.md`): **n8n es el panel de control humano, no el motor del pipeline.**
> Los pasos pesados (transcripción, guion, TTS, render) los ejecutan workers TS que consumen la tabla
> `jobs` en Postgres. n8n dispara, observa, pide aprobación y notifica. Si n8n se cae, el pipeline
> sigue operable desde la CLI.

## Contrato entre n8n y los workers

- **Estado en Postgres**: tabla `videos` con la máquina de estados
  `idea → guion → render → preview → aprobado → publicado → metricas` (+ `error`, `rechazado`).
- **Cola**: tabla `jobs` (`id, video_id, paso, estado, intentos, payload, error, created_at, updated_at`).
  Los workers hacen polling con `FOR UPDATE SKIP LOCKED`; n8n solo inserta jobs y lee estados.
- **Callbacks**: cada worker, al terminar un paso, hace `POST {N8N_WEBHOOK_BASE_URL}/webhook/paso-terminado`
  con `{ video_id, paso, resultado: "ok" | "error", detalle }`.
- **Artefactos**: siempre en `media/<video_id>/` (audio.wav, transcripcion.json, guion.json,
  narracion.mp3, final.mp4). Nunca se pasan binarios por n8n — solo rutas e IDs.

```
Telegram ◄──────────────┐
   │ comandos            │ notificaciones/aprobación
   ▼                     │
┌─────────────────────── n8n ───────────────────────┐
│ WF1 entrada   WF2 dispatcher   WF3 aprobación      │
│ WF4 publicar  WF5 métricas     WF6 watchdog        │
└───────┬───────────────▲───────────────────────────┘
        │ INSERT jobs   │ webhook paso-terminado
        ▼               │
   Postgres (videos, jobs, metricas) ◄── workers TS (ai, render) ── media/
```

## WF1 — Entrada por Telegram

**Trigger:** Telegram Trigger (mensajes al bot).

| Nodo | Función |
|---|---|
| Telegram Trigger | Recibe `/idea <descripcion|url>`, `/estado`, `/cola`, `/cancelar <id>` |
| Switch (comando) | Enruta según comando |
| Postgres | `/idea`: INSERT en `videos` (estado `idea`) + job `analisis` |
| Postgres | `/estado`, `/cola`: SELECT resumen de videos activos |
| Telegram | Responde con confirmación e `id` del video |

## WF2 — Dispatcher del pipeline

**Trigger:** Webhook `POST /webhook/paso-terminado` (lo llaman los workers).

| Nodo | Función |
|---|---|
| Webhook | Recibe `{video_id, paso, resultado, detalle}` |
| IF resultado = error | → notificar por Telegram con detalle y marcar video `error` |
| Switch (paso) | Mapea paso terminado → siguiente paso: `analisis→guion→tts→render` |
| Postgres | UPDATE estado del video + INSERT del siguiente job |
| IF paso = render | → en vez de encolar, dispara **WF3** (Execute Workflow) |

El conocimiento del orden del pipeline vive aquí (un solo Switch), no repartido por los workers:
cambiar el orden o insertar un paso nuevo = editar un nodo.

## WF3 — Aprobación de preview (el corazón del "bot propone, tú apruebas")

**Trigger:** Execute Workflow desde WF2 (video en estado `preview`).

| Nodo | Función |
|---|---|
| Telegram (sendVideo) | Envía `media/<id>/final.mp4` + guion + captions propuestos |
| Telegram (botones inline) | `✅ Aprobar` · `❌ Rechazar` · `📝 Regenerar guion` · `🔊 Regenerar voz` |
| Telegram Trigger (callback) | Espera el botón pulsado |
| Switch (acción) | Aprobar → estado `aprobado` + Execute WF4 · Rechazar → `rechazado` · Regenerar X → re-encola job `guion` o `tts` (la idempotencia de los pasos lo permite) |

Nota: si el mp4 supera el límite de Telegram (50 MB vía Bot API), enviar un preview
recomprimido (`media/<id>/preview.mp4`, generado por el worker de render) y un enlace local.

## WF4 — Publicación

**Trigger:** Execute Workflow desde WF3 (video `aprobado`), o Schedule (horarios pico por red).

| Nodo | Función |
|---|---|
| Postgres | SELECT videos `aprobado` pendientes + captions por red |
| HTTP Request | POST al intermediario (`publish(video, meta, red)`) — un item por red |
| Postgres | UPDATE `publicado` + guarda `post_id` por red para métricas |
| Telegram | Confirma publicación con enlaces |

El nodo HTTP apunta a un endpoint propio del worker publicador (módulo swapeable), no
directamente al intermediario: cambiar de Upload-Post a Blotato no toca el workflow.

## WF5 — Métricas (feedback loop)

**Trigger:** Schedule (cron diario, p. ej. 08:00).

| Nodo | Función |
|---|---|
| Postgres | SELECT videos `publicado` con `post_id` |
| HTTP Request | GET métricas al intermediario por cada post |
| Postgres | UPSERT en `metricas` (views, likes, shares, retención) |
| IF (semanal) | Los domingos: resumen top/bottom por hook/formato/horario → Telegram |

## WF6 — Watchdog (opcional, recomendado)

**Trigger:** Schedule (cada 15 min).

| Nodo | Función |
|---|---|
| Postgres | SELECT jobs `en_proceso` sin actualizar hace > 30 min, o videos en `error` |
| Telegram | Alerta con id, paso y último error |

Cubre el caso real conocido: renders que fallan con errores confusos cuando el disco se llena.

## Convenciones

- Los workflows se exportan como JSON a `orchestrator/` y se versionan (nombres: `wf1-entrada.json`…).
- Credenciales (Telegram, Postgres, intermediario) viven en n8n, nunca en los JSON exportados.
- Todo webhook de n8n valida un header `X-VF-Token` (secreto compartido en `.env`).
- Orden de implementación sugerido: **WF1 + WF2** (con workers de Fase 1) → **WF3** → WF4 → WF5/WF6 (Fase 3–4).
