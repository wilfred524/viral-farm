# Decisiones del proyecto

## Confirmadas

| Decisión | Elección | Fecha |
|---|---|---|
| Plataformas | TikTok, Instagram Reels, YouTube Shorts, X/Twitter | 2026-07-22 |
| Formato inicial | Movie recaps (escenas + narración), pipeline agnóstico al nicho | 2026-07-22 |
| Publicación | Servicio intermediario (una API → 4 redes) | 2026-07-22 |
| Interfaz de control | Telegram + n8n | 2026-07-22 |
| Stack | Node.js + TS, Remotion, ffmpeg, Whisper local | 2026-07-22 |
| Base de datos | **PostgreSQL** (ya instalado; reemplaza a SQLite — locking multi-contenedor) | 2026-07-24 |
| Orquestación | **n8n = capa de control humano** (Telegram, aprobación, cron); el pipeline lo motorizan workers TS vía tabla `jobs` en Postgres (`FOR UPDATE SKIP LOCKED`). Ver `n8n-workflows.md` | 2026-07-24 |
| Despliegue | Docker híbrido: n8n/Postgres/servicios livianos en Compose; render y Whisper nativos en Windows (GPU/rendimiento/disco) | 2026-07-24 |
| Formato de la Fase 1 | **Clipping**: un video largo → N clips verticales 9:16 con subtítulos, en vez del recap narrado. Fija el producto de `Propuesta_Tecnica_Pipeline_Video.pdf` | 2026-07-29 |
| Narración | **Ducking, misma duración**: el LLM parte cada clip en tramos `narracion` \| `original`; donde hay voz, el audio ambiental baja a −18 dB. El clip nunca se alarga | 2026-07-29 |
| Transcripción | **faster-whisper** (Python, CPU por defecto) con `word_timestamps` — sin timings por palabra no hay subtítulos karaoke | 2026-07-29 |
| TTS | **Edge-TTS** con `boundary="WordBoundary"`; se invoca como subproceso, interfaz swapeable | 2026-07-29 |
| Montaje y render | ffmpeg del sistema para recorte/reencuadre/mezcla (`base.mp4`) + Remotion para subtítulos y plantilla (`final.mp4`) | 2026-07-29 |

## Pendientes

- [ ] **Elegir intermediario de publicación** — comparar Upload-Post vs Blotato vs Metricool: precio, redes soportadas, API de métricas, límites de subida.
- [ ] **Presupuesto IA mensual** — decidir escenario según la matriz de abajo.
- [ ] **Espacio en disco** — el worker de render necesita workspace; C: sigue con ~4,5 GB libres. El CLI aborta el render por debajo de `MIN_GB_LIBRES` (8 por defecto).
- [ ] **Modelo del LLM** — la Fase 1 usa `claude-opus-5` por defecto (`LLM_MODELO`); medir coste real por video y bajar a Sonnet/Haiku si la calidad del gancho lo permite.

## Matriz de costos IA (por video de ~1–3 min; mes = 60 videos, 2/día)

| Componente | Mínimo | Medio | Alto |
|---|---|---|---|
| Guion + captions (LLM) | Haiku: ~$0.02 | Sonnet: ~$0.15 | Sonnet/Opus + iteración: ~$0.40 |
| Análisis visual de escenas | ~$0.05 | ~$0.15 | ~$0.40 |
| Transcripción | Whisper local: $0 | Whisper local: $0 | API: ~$0.02 |
| TTS narración | Edge-TTS: $0 | OpenAI TTS: ~$0.05 | ElevenLabs: ~$0.30 |
| B-roll/imagen generativa | $0 | ~$0.10 | $1–4 (video generativo) |
| Render | Local: $0 | Local: $0 | Remotion Lambda: ~$0.05 |
| **Costo por video** | **~$0.07** | **~$0.45** | **~$2–5** |
| **IA/mes (60 videos)** | **~$5** | **~$27** | **~$120–300** |
| Intermediario publicación | ~$20–30/mes | ~$30–50/mes | ~$50–100/mes |
| n8n | self-hosted: $0 | self-hosted: $0 | cloud: $24/mes |
| **Total mensual** | **~$25–35** | **~$60–80** | **~$200–425** |

**Recomendación:** arrancar en mínimo→medio y escalar según métricas reales.
