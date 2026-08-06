# ViralFarm 🎬🤖

Bot que **manipula, edita y publica videos/imágenes en redes sociales** con potencial viral, para hacer crecer cuentas propias de forma sistemática. Formato inicial: **movie recaps** (escenas de películas con narración), con arquitectura agnóstica al nicho.

**Principio de diseño:** el bot propone, tú apruebas. Aprobación por Telegram antes de cada publicación.

> ⚠ **Este README documenta la implementación actual (Fase 1, TypeScript)**, funcional y en
> proceso de ser reemplazada. La arquitectura objetivo —reescritura en Python, capas de
> percepción y decisión, radar de oportunidades— está en
> [`docs/arquitectura.md`](docs/arquitectura.md), que es el documento canónico.

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
                                   └───► PostgreSQL ◄┘   TikTok · IG · YT · X
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
| `db/` | Esquema PostgreSQL y migraciones |
| `docs/` | Decisiones, matriz de costos, comparativas |

## Pipeline de contenido

Una película entra y sale una **serie de episodios verticales** listos para aprobación, que se publican en orden, uno por entrega:

1. **Ingesta** — ffprobe valida el fuente y crea su carpeta de trabajo (`media/<video_id>/`)
2. **Transcripción** — faster-whisper local, con timestamps por palabra; detecta el idioma hablado
3. **Serie de episodios** — el LLM parte la película en entregas ordenadas; el código valida duración, orden, solapes y cobertura, y alinea los cortes a cambio de plano
4. **Guion** — por episodio: recap de la entrega anterior, hook, reparto en tramos `narracion` \| `original`, caption y hashtags
5. **Voz** — Edge-TTS sintetiza los tramos narrados y devuelve timings por palabra
6. **Montaje** — ffmpeg recorta, reencuadra a 1080×1920 y mezcla la voz con el audio ambiental atenuado (**ducking**, sin alargar el clip) → `base.mp4`
7. **Render** — Remotion añade subtítulos karaoke y plantilla → `final.mp4` + `preview.mp4`

Después (Fases 2–3): **QC + preview** por Telegram con botón de aprobación, **publicación** vía el intermediario y **feedback loop** de métricas.

## Uso (Fase 1)

```bash
npm install
pip install faster-whisper edge-tts
cp .env.example .env        # y completa ANTHROPIC_API_KEY

npm run cli -- run <pelicula.mp4>                  # serie completa
npm run cli -- run <video.mp4> --formato virales   # clips sueltos de 20-60 s (formato legado)
npm run cli -- run <video.mp4> --sin-tts           # solo audio original, sin narración
npm run cli -- help                                # pasos sueltos: ingest, transcribe, clips, guion, tts, montar, render
```

Cada paso es idempotente: reejecutar `run` retoma donde se quedó sin repetir transcripciones ni llamadas al LLM. `--force` rehace el paso indicado.

### Formato serie

Una película no da "los cinco mejores momentos": da una historia. El formato por defecto la parte en **episodios de 120 a 360 segundos** (objetivo 270) que se publican en orden:

- **Orden cronológico estricto.** Puede haber huecos *entre* episodios donde el material es relleno; nunca *dentro* de uno.
- **Cada episodio cierra su arco** (planteamiento, cumbre, desenlace) **y abre una tensión nueva** en los últimos segundos, que resuelve el siguiente. Ese es el motor: el espectador vuelve a por la entrega siguiente.
- **Recap narrado de 8 s** al abrir, desde la parte 2. Lo inserta el código, no el modelo, así que la invariante se cumple aunque el LLM lo ignore.
- **Numeración** en pantalla (chapa `n / N` sobre el hook) y en el caption, con llamada a seguir la cuenta — todo en el idioma de salida.
- **Cortes alineados a cambio de plano**: se detectan escenas en ventanas de ±3 s alrededor de cada corte propuesto (no en toda la película), descartando los que partirían una palabra. `--sin-escenas` lo desactiva.

Dos límites que el código impone y que existen por el riesgo de copyright (ver `docs/riesgos.md`): los episodios **no pueden cubrir más del 60 %** de la película (error duro) y cada uno lleva **entre 40 % y 65 % de narración propia** (aviso).

Objetivo **TikTok**: Reels y Shorts topan en 180 s y no admiten estos episodios sin recortarlos.

### Sin clave de API

`LLM_RESPUESTAS_DIR` hace que los pasos `clips` y `guion` lean su respuesta de disco en vez de llamar a la API — y la validen contra el mismo esquema Zod que una respuesta real. Cuando sí hay clave, ese directorio funciona como caché de lo ya pagado.

```bash
LLM_RESPUESTAS_DIR=./media/pruebas-llm npm run cli -- clips --video-id <id>
```

### Idiomas

El pipeline distingue el idioma **del material** del idioma **del contenido que produce**, y no tienen por qué coincidir:

```bash
npm run cli -- run pelicula.mp4                              # detecta el idioma y narra en ese mismo
npm run cli -- run pelicula.mp4 --idioma en --idioma-salida es   # audio en inglés → clips en español
```

- `--idioma` (o `IDIOMA_FUENTE`): idioma hablado en el video. Por defecto `auto` — lo detecta Whisper. Forzar un idioma equivocado **no da error**: devuelve una transcripción traducida a medias e inservible, así que solo conviene fijarlo cuando la detección falla.
- `--idioma-salida` (o `IDIOMA_SALIDA`): idioma de narración, hook, caption y hashtags. Vacío = el del audio.

La voz de Edge-TTS y el ritmo de habla que decide cuánto texto cabe en cada tramo salen del catálogo de `src/lib/idiomas.ts` (es, en, pt, fr, it, de; el resto cae a una voz multilingüe). `TTS_VOZ` fuerza una voz concreta para todos los idiomas.

Cuando el idioma de salida difiere del original, el guionista se apoya más en tramos narrados: el audio ambiental sigue ahí, pero el público no entiende lo que se dice.

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

Node.js + TypeScript · Remotion 4.x · ffmpeg · n8n (self-hosted, Docker) · PostgreSQL · faster-whisper · API Anthropic · Edge-TTS/OpenAI TTS

## Documentación

- [`docs/decisiones.md`](docs/decisiones.md) — matriz de costos IA y decisiones pendientes
- [`docs/riesgos.md`](docs/riesgos.md) — copyright, ToS de plataformas, dependencias
