# ViralFarm 🎬🤖

Bot que **manipula, edita y publica videos/imágenes en redes sociales** con potencial viral, para hacer crecer cuentas propias de forma sistemática. Formato inicial: **movie recaps** (escenas de películas con narración), con arquitectura agnóstica al nicho.

**Principio de diseño:** el bot propone, tú apruebas. Aprobación por Telegram antes de cada publicación.

## Plataformas objetivo

TikTok · Instagram Reels · YouTube Shorts · X/Twitter — vía **servicio intermediario de publicación** (una sola API para las 4 redes).

## Arquitectura

```
┌────────────┐   comandos/aprobaciones   ┌─────────────────────┐
│  Telegram   │◄─────────────────────────►│   n8n (orquestador)  │
│  (control)  │                           │  webhooks + colas    │
└────────────┘                           └──────────┬──────────┘
                                                    │ HTTP/jobs
                                   ┌────────────────┼────────────────┐
                                   ▼                ▼                ▼
                           ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                           │ Worker IA     │ │ Worker Render │ │ Publicador    │
                           │ (Node/TS)     │ │ Remotion +    │ │ intermediario │
                           │ guion, TTS,   │ │ ffmpeg        │ │ (Upload-Post/ │
                           │ análisis visual│ │ (local)       │ │ Blotato/...)  │
                           └──────────────┘ └──────────────┘ └──────┬───────┘
                                   │                │               ▼
                                   └────► SQLite ◄──┘   TikTok · IG · YT · X
                                    (estado, cola, métricas)
```

## Estructura del repo

| Carpeta | Contenido |
|---|---|
| `orchestrator/` | Flujos de n8n exportados (JSON) |
| `workers/render/` | Worker de montaje: Remotion (plantillas parametrizadas) + ffmpeg |
| `workers/ai/` | Worker IA: análisis visual, guion, captions, TTS |
| `bot/` | Bot de Telegram (si el nodo de n8n se queda corto → grammY) |
| `db/` | Esquema SQLite y migraciones |
| `docs/` | Decisiones, matriz de costos, comparativas |

## Pipeline de contenido

1. **Ingesta** — video fuente → ffmpeg extrae audio + frames de muestreo
2. **Análisis** — Whisper local transcribe; visión LLM mapea escenas a timestamps
3. **Guion** — LLM escribe narración viral (hook en 1.5 s, tensión, payoff) + captions/hashtags por red
4. **Voz** — TTS de la narración
5. **Montaje** — ffmpeg corta/comprime → Remotion monta subtítulos karaoke, zooms, plantilla de marca
6. **QC + preview** — Telegram → aprobación con botón → publicación programada
7. **Feedback loop** — cron recoge métricas → el LLM ajusta los siguientes guiones

## Estado del video (máquina de estados)

`idea → guion → render → preview → aprobado → publicado → métricas`

## Roadmap

- [ ] **Fase 0 — Fundación:** repo, estructura, elección de intermediario de publicación
- [ ] **Fase 1 — Pipeline manual:** CLI end-to-end (fuente → transcripción → guion → TTS → montaje → mp4)
- [ ] **Fase 2 — Control por Telegram:** `/idea`, `/preview`, botones de aprobación, n8n self-hosted
- [ ] **Fase 3 — Publicación multi-red:** API del intermediario, horarios pico, captions por red
- [ ] **Fase 4 — Feedback viral:** métricas → rendimiento por hook/formato/horario → prompts alimentados con ganadores

## Stack

Node.js + TypeScript · Remotion 4.x · ffmpeg · n8n (self-hosted, Docker) · SQLite · Whisper.cpp · API Anthropic · Edge-TTS/OpenAI TTS

## Documentación

- [`docs/decisiones.md`](docs/decisiones.md) — matriz de costos IA y decisiones pendientes
- [`docs/riesgos.md`](docs/riesgos.md) — copyright, ToS de plataformas, dependencias
