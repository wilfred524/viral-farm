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
| `src/` | CLI y pasos del pipeline (`src/pasos/`), utilidades (`src/lib/`) |
| `remotion/` | Composición del clip vertical: hook, subtítulos karaoke, plantilla |
| `scripts/` | Subprocesos Python: transcripción (faster-whisper) y TTS (Edge-TTS) |
| `orchestrator/` | Flujos de n8n exportados (JSON) |
| `workers/render/` | Worker de montaje: Remotion (plantillas parametrizadas) + ffmpeg |
| `workers/ai/` | Worker IA: análisis visual, guion, captions, TTS |
| `bot/` | Bot de Telegram (si el nodo de n8n se queda corto → grammY) |
| `db/` | Esquema SQLite y migraciones |
| `docs/` | Decisiones, matriz de costos, comparativas |

## Pipeline de contenido

Un video largo entra y salen N clips verticales listos para aprobación:

1. **Ingesta** — ffprobe valida el fuente y crea su carpeta de trabajo (`media/<video_id>/`)
2. **Transcripción** — faster-whisper local, con timestamps por palabra
3. **Selección de clips** — el LLM elige los fragmentos con más gancho; el código valida rangos, solapes y fronteras de frase
4. **Guion** — por clip: hook de 1.5 s, reparto en tramos `narracion` \| `original`, caption y hashtags
5. **Voz** — Edge-TTS sintetiza los tramos narrados y devuelve timings por palabra
6. **Montaje** — ffmpeg recorta, reencuadra a 1080×1920 y mezcla la voz con el audio ambiental atenuado (**ducking**, sin alargar el clip) → `base.mp4`
7. **Render** — Remotion añade subtítulos karaoke y plantilla → `final.mp4` + `preview.mp4`

Después (Fases 2–3): **QC + preview** por Telegram con botón de aprobación, **publicación** vía el intermediario y **feedback loop** de métricas.

## Uso (Fase 1)

```bash
npm install
pip install faster-whisper edge-tts
cp .env.example .env        # y completa ANTHROPIC_API_KEY

npm run cli -- run <video.mp4> --n 5          # pipeline completo
npm run cli -- run <video.mp4> --sin-tts      # solo audio original, sin narración
npm run cli -- help                           # pasos sueltos: ingest, transcribe, clips, guion, tts, montar, render
```

Cada paso es idempotente: reejecutar `run` retoma donde se quedó sin repetir transcripciones ni llamadas al LLM. `--force` rehace el paso indicado.

Artefactos por video:

```
media/<video_id>/
  fuente.json  audio.wav  transcripcion.json  clips.json
  clips/<n>/   guion.json  narracion/  narracion.json  base.mp4  final.mp4  preview.mp4
```

## Estado del video (máquina de estados)

`idea → guion → render → preview → aprobado → publicado → métricas`

## Roadmap

- [x] **Fase 0 — Fundación:** repo, estructura, elección de intermediario de publicación
- [x] **Fase 1 — Pipeline manual:** CLI end-to-end (fuente → transcripción → clips → guion → TTS → montaje → mp4 vertical)
- [ ] **Fase 2 — Control por Telegram:** `/idea`, `/preview`, botones de aprobación, n8n self-hosted
- [ ] **Fase 3 — Publicación multi-red:** API del intermediario, horarios pico, captions por red
- [ ] **Fase 4 — Feedback viral:** métricas → rendimiento por hook/formato/horario → prompts alimentados con ganadores

## Stack

Node.js + TypeScript · Remotion 4.x · ffmpeg · n8n (self-hosted, Docker) · SQLite · Whisper.cpp · API Anthropic · Edge-TTS/OpenAI TTS

## Documentación

- [`docs/decisiones.md`](docs/decisiones.md) — matriz de costos IA y decisiones pendientes
- [`docs/riesgos.md`](docs/riesgos.md) — copyright, ToS de plataformas, dependencias
