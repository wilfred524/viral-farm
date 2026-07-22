# Decisiones del proyecto

## Confirmadas

| Decisión | Elección | Fecha |
|---|---|---|
| Plataformas | TikTok, Instagram Reels, YouTube Shorts, X/Twitter | 2026-07-22 |
| Formato inicial | Movie recaps (escenas + narración), pipeline agnóstico al nicho | 2026-07-22 |
| Publicación | Servicio intermediario (una API → 4 redes) | 2026-07-22 |
| Interfaz de control | Telegram + n8n | 2026-07-22 |
| Stack | Node.js + TS, Remotion, ffmpeg, SQLite, Whisper local | 2026-07-22 |

## Pendientes

- [ ] **Elegir intermediario de publicación** — comparar Upload-Post vs Blotato vs Metricool: precio, redes soportadas, API de métricas, límites de subida.
- [ ] **Presupuesto IA mensual** — decidir escenario según la matriz de abajo.
- [ ] **TTS** — arrancar con Edge-TTS (gratis) y evaluar si la voz es cuello de botella.
- [ ] **Espacio en disco** — el worker de render necesita workspace; C: está ~99% lleno.

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
