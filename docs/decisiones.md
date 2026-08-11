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
| Idiomas | **Dos idiomas independientes**: el del audio (detectado por Whisper, `IDIOMA_FUENTE=auto`) y el del contenido generado (`IDIOMA_SALIDA`, por defecto el mismo). Catálogo de voz Edge-TTS y ritmo de habla por idioma en `src/lib/idiomas.ts` | 2026-07-30 |
| Formato principal | **Serie de episodios** (`--formato serie`, por defecto): la película se parte en entregas de 120-360 s (objetivo 270) que se publican en orden. Cada una cierra su arco y abre una tensión nueva; la siguiente la resuelve. El formato viral de 20-60 s queda como `--formato virales` | 2026-07-31 |
| Serialidad | Numeración en pantalla (chapa "n / N" sobre el hook) y en el caption, más **recap narrado de 8 s** al abrir cada episodio desde el segundo. El recap lo inserta el código, no el modelo | 2026-07-31 |
| Cobertura y transformatividad | Los episodios no pueden cubrir más del **60 %** del fuente (error duro) y cada uno lleva entre **40 % y 65 % de narración** (aviso). Ver `riesgos.md` | 2026-07-31 |
| Plataforma objetivo | **TikTok primero**: Reels y Shorts topan en 180 s y no admiten el formato serie tal cual. Las variantes por red quedan para la Fase 3 | 2026-07-31 |
| Cortes | Los límites de episodio se alinean a **cambio de plano** (ffmpeg `select=gt(scene,0.3)` en ventanas de ±3 s, ~0,26 s por ventana), con reserva a frontera de frase. Nunca se corta partiendo una palabra | 2026-07-31 |
| **Lenguaje** | **Python en todo el sistema**, reescritura completa. Es el que mantiene el autor, y el código que más se toca son los prompts y las reglas del formato. Whisper y Edge-TTS ya eran Python invocados por subproceso; pasan a llamadas directas. Stack: uv · Pydantic v2 · Typer · pytest/ruff/mypy | 2026-08-05 |
| **Estrategia de migración** | **Reescritura limpia**, no traducción 1:1: se aplica la reorganización (dominio puro + adaptadores + pasos) desde el primer día. Los artefactos JSON existentes hacen de *golden files* para verificar paridad | 2026-08-05 |
| **Render** | **Remotion se elimina.** Hook, chapa `n/N` y karaoke pasan a **ASS/libass** generado desde Python y quemado con ffmpeg. Saca Node del repo. **Medido el 2026-08-06**: 6,0 min frente a 51,3 min de Remotion para los mismos 697 s de vídeo — 8,6× más rápido, salida 35 % más pequeña y visualmente equivalente. El paso queda tras una interfaz por si hiciera falta un motor de composición | 2026-08-05 |
| **Modelo de sistema** | De **pipeline lineal a ciclo con criterio**: percepción (trazas de audio y video, sin IA) → comprensión (visión dirigida por esas señales) → decisión (candidatos con scoring desglosado) → generación con crítico → montaje. Cada capa filtra antes de que la siguiente gaste | 2026-08-05 |
| **Visión** | **Muestreo dirigido, no ciego**: los frames que se mandan al LLM multimodal se eligen donde las señales objetivas indican evento (~60 imágenes en vez de ~540 en una película de 90 min) | 2026-08-05 |
| **Auditabilidad** | Toda decisión persiste su evidencia: score desglosado por componentes, versión de prompt, modelo y parámetros. Se separa lo que el sistema **consideró** (`candidatos.json`) de lo que **eligió** (`serie.json`) | 2026-08-05 |
| **Radar de oportunidades** | Subsistema aparte, con reloj propio, que decide **qué producir**. Fuentes: TMDB y Wikipedia (demanda y olvido), YouTube (saturación), TikTok Creative Center (formato). Descartados los scrapers no oficiales de TikTok | 2026-08-05 |
| **Estrategia de contenido** | **Catálogo olvidado, no tendencia**: `calidad_histórica × olvido_actual × (1−saturación) × factibilidad × (1−riesgo)`. Se busca la brecha entre calidad validada en su momento y atención actual nula. Ver `riesgos.md` | 2026-08-05 |

## Pendientes

- [ ] **Elegir intermediario de publicación** — comparar Upload-Post vs Blotato vs Metricool: precio, redes soportadas, API de métricas, límites de subida.
- [ ] **Presupuesto IA mensual** — decidir escenario según la matriz de abajo.
- [ ] **Espacio en disco** — el worker de render necesita workspace; C: tenía ~4,5 GB libres el 2026-07-29 y ~11 GB tras la limpieza del 2026-07-30 (medición vigente en `riesgos.md`). El CLI aborta el render por debajo de `MIN_GB_LIBRES` (8 por defecto).
- [ ] **Modelo del LLM** — el default del **código** es `claude-sonnet-5` (`src/config.ts`, `viralfarm/config.py`); `.env.example` propone `claude-opus-5`, así que quien copie la plantilla usará Opus. Decidir cuál queda como default real y alinear ambos. Las capas de visión, scoring y crítico añaden llamadas: recalcular la matriz de costos de abajo.

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
