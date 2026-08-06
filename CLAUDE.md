# ViralFarm — contexto del proyecto

Bot que edita y publica videos/imágenes con potencial viral en redes sociales (TikTok, IG Reels, YT Shorts, X) para crecer cuentas propias. Formato inicial: movie recaps (escenas + narración), pipeline agnóstico al nicho. Control por Telegram (motor por decidir: n8n o servicio propio); publicación vía servicio intermediario. **Idioma de trabajo: español.**

## Documentos fuente de verdad
- **`docs/arquitectura.md` — DOCUMENTO CANÓNICO.** Arquitectura objetivo: los tres subsistemas
  (Radar, Producción, Control), las cinco capas, el pipeline paso a paso, la estructura de
  código Python y el roadmap. Manda sobre cualquier otro documento.
- `docs/decisiones.md` — decisiones confirmadas/pendientes y matriz de costos IA por escenario.
- `docs/riesgos.md` — copyright, criterio de selección de material, ToS multi-cuenta.
- `README.md` — describe la implementación **actual** en TypeScript (Fase 1), que sigue siendo
  funcional mientras se migra. Su sección de arquitectura está superada por `arquitectura.md`.

Leer `arquitectura.md` antes de implementar nada. Mantenerlos actualizados cuando se tome una
decisión nueva.

## Rumbo actual (2026-08-05)

**El proyecto se reescribe entero en Python.** Motivo: es el lenguaje que mantiene el autor, y
el ecosistema de análisis de audio y visión vive ahí. Decisiones asociadas:

- **Remotion se elimina**: los subtítulos karaoke, el hook y la chapa `n/N` pasan a ASS/libass
  generado desde Python y quemado con ffmpeg. Sin Node en el repo.
- **De pipeline lineal a sistema con criterio**: se añaden capas de percepción (trazas de audio
  y video, sin IA), comprensión (visión dirigida por esas señales), decisión (candidatos con
  scoring desglosado) y refinamiento (crítico del guion).
- **Radar de oportunidades**: subsistema que decide *qué* producir, apuntando a **catálogo
  olvidado** (calidad histórica alta + atención actual baja + saturación nula), no a tendencias.
- Migración por **reescritura limpia**, verificada contra los artefactos existentes como
  golden files.

Mientras dure la migración, el pipeline TypeScript de la Fase 1 sigue siendo el que funciona.

## Estado actual del código (TypeScript, a sustituir)
- **Fase 0 (fundación) y Fase 1 (pipeline CLI) completadas.**
- La Fase 1 implementa **clipping**: video largo → piezas 9:16 con subtítulos, con narración TTS opcional mezclada por **ducking** (la pieza conserva su duración). Comandos: `ingest, transcribe, clips, guion, tts, montar, render, run, cortes`.
- **Formato serie** (por defecto, Fase 1.5): la película se parte en episodios de 120-360 s que se publican en orden, cada uno con recap narrado, arco propio y cierre en tensión. `--formato virales` recupera los clips sueltos de 20-60 s.
- **Multiidioma**: el idioma del audio (detectado, `--idioma`) y el del contenido generado (`--idioma-salida`) son independientes. Catálogo de voces, ritmo de habla y textos de serie en `src/lib/idiomas.ts`.
- **Sin clave de API**: `LLM_RESPUESTAS_DIR` hace que `clips` y `guion` lean su respuesta de disco, validada con el mismo esquema Zod. Es como se prueba el pipeline hoy.
- Pasos idempotentes sobre artefactos en `media/<video_id>/`; diseñados para que el worker de la Fase 2 solo tenga que invocarlos.
- **Siguiente: migración a Python** (ver `docs/arquitectura.md` §10). El control por Telegram
  queda después, y el motor (n8n vs. servicio propio en FastAPI) está por decidir.
- Pendiente decidir: ver `docs/arquitectura.md` §11 (decisiones abiertas).

### Defectos conocidos del código TypeScript
No se arreglan aquí: los corrige la reescritura (`arquitectura.md` §9.3). Conviene conocerlos
para no confiar de más en los resultados actuales:
- **El caché de `LLM_RESPUESTAS_DIR` no lleva `videoId` en la clave** (`src/lib/llm.ts`): con
  una segunda película se sirve el guion de la primera, y pasa la validación Zod.
- Cero tests. La lógica frágil solo se verifica renderizando.
- El LLM solo ve texto: es ciego a la imagen y a la traza de audio.

## Notas de implementación (Fase 1)
- `typescript` está fijado en 5.9: el bundler de Remotion usa `typescript.sys`, que TS 7 no expone.
- `remotion/` tiene su propio `tsconfig.json` (`moduleResolution: Bundler`) porque webpack no resuelve los imports con extensión `.js` que exige NodeNext en `src/`.
- Edge-TTS 7.x emite `SentenceBoundary` por defecto: hay que pedir `boundary="WordBoundary"` para los timings por palabra.
- faster-whisper se invoca con `--dispositivo cpu`; con `auto` elige CUDA y falla si no están las libs de cuBLAS.
- Forzar en Whisper un idioma que no es el del audio **no da error**: traduce sobre la marcha y devuelve texto degradado (mezcla de idiomas, palabras inventadas). Por eso `IDIOMA_FUENTE` es `auto` por defecto.
- La detección de escenas usa `-ss` **antes** de `-i` (seek rápido) y `-copyts`, para que `pts_time` salga en segundos absolutos del fuente. Sin `-copyts` los tiempos son relativos a la ventana.
- En formato serie el paso `guion` es una **cadena de llamadas dependientes**: cada episodio necesita el resumen del anterior. No se paraleliza, y `--force` sobre la serie debe correrse entera y en orden — regenerar sueltos con `--clip` desincroniza los recaps del contenido.
- El bundle de Remotion usa `symlinkPublicDir: true`; sin eso copiaría todo `MEDIA_DIR` en cada render.

## Principios de diseño
- **El bot propone, el usuario aprueba**: nunca publicar sin aprobación humana (botón en Telegram).
- El publicador es un módulo swapeable: `publish(video, meta, red)`.
- Máquina de estados por video: `idea → guion → render → preview → aprobado → publicado → métricas`.
- Un solo lenguaje en todo el sistema (hoy TypeScript; **se migra a Python**, ver `docs/arquitectura.md`).
- Persistencia: **PostgreSQL** desde 2026-07-24 (sustituyó a SQLite por locking multi-contenedor).

## Aprendizajes técnicos heredados del proyecto `my-video` (C:\Users\GAF\workspace\my-video)
Proyecto hermano donde se validó el stack de video; consultarlo como referencia de código Remotion funcionando.

- **ffmpeg**: el bundled de Remotion (`@remotion/compositor-win32-*/ffmpeg.exe`) es un build MÍNIMO (solo scale/trim/crop/transpose/rotate). Usar el ffmpeg completo 8.1.2 del sistema: `C:\Users\GAF\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe` (tiene unsharp, eq, hqdn3d, drawtext, tile, etc.).
- **Video vertical**: los MOV de móvil suelen venir con `rotation=90` en metadata; ffmpeg autorrota. Extraer con `scale=1080:1920` y componer en vertical, nunca forzar 16:9 (deforma).
- **Análisis de escenas**: extraer frames espaciados con `-ss <t> -frames:v 1` y analizarlos con visión LLM para mapear acciones a timestamps — validado, funciona bien.
- **Remotion**: `CameraMotionBlur`/`Trail` NO deben envolver `OffthreadVideo` (refetch sub-frame falla); `random()` siempre sembrado; `loadFont()` a nivel de módulo con weights/subsets limitados; `visualizeAudio` requiere null-guard y numberOfSamples potencia de 2; TransitionSeries: duración total = Σescenas − Σtransiciones.
- **Render local**: ~4–7 min por 1200 frames 1080×1920; los renders fallan con errores confusos ("Failed to fetch", 500) cuando el **disco está lleno** — C: anda ~99% ocupado, verificar espacio antes de renderizar.

## Convenciones
- Commits en español, mensaje descriptivo de fase/módulo.
- No comitear media (`.gitignore` ya lo excluye); secretos solo en `.env` (plantilla en `.env.example`).
