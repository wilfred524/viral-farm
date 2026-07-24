# ViralFarm — contexto del proyecto

Bot que edita y publica videos/imágenes con potencial viral en redes sociales (TikTok, IG Reels, YT Shorts, X) para crecer cuentas propias. Formato inicial: movie recaps (escenas + narración), pipeline agnóstico al nicho. Control por Telegram + n8n; publicación vía servicio intermediario. **Idioma de trabajo: español.**

## Documentos fuente de verdad
- `README.md` — arquitectura completa, pipeline de 7 pasos, roadmap de 5 fases, stack.
- `docs/decisiones.md` — decisiones confirmadas/pendientes y matriz de costos IA por escenario.
- `docs/riesgos.md` — copyright (movie recaps), ToS multi-cuenta, dependencia del intermediario.

Leer los tres antes de implementar cualquier fase. Mantenerlos actualizados cuando se tome una decisión nueva.

## Estado actual
- **Fase 0 (fundación) completada**: estructura del repo, docs, git inicializado.
- **Siguiente: Fase 1** — CLI end-to-end: video fuente → transcripción (Whisper local) → guion (LLM) → TTS → montaje (Remotion + ffmpeg) → mp4 vertical 1080×1920.
- Pendiente decidir: intermediario de publicación (Upload-Post vs Blotato vs Metricool) y presupuesto IA.

## Principios de diseño
- **El bot propone, el usuario aprueba**: nunca publicar sin aprobación humana (botón en Telegram).
- El publicador es un módulo swapeable: `publish(video, meta, red)`.
- Máquina de estados por video: `idea → guion → render → preview → aprobado → publicado → métricas`.
- SQLite hasta que duela; un solo lenguaje (Node + TypeScript).

## Aprendizajes técnicos heredados del proyecto `my-video` (C:\Users\GAF\my-video)
Proyecto hermano donde se validó el stack de video; consultarlo como referencia de código Remotion funcionando.

- **ffmpeg**: el bundled de Remotion (`@remotion/compositor-win32-*/ffmpeg.exe`) es un build MÍNIMO (solo scale/trim/crop/transpose/rotate). Usar el ffmpeg completo 8.1.2 del sistema: `C:\Users\GAF\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe` (tiene unsharp, eq, hqdn3d, drawtext, tile, etc.).
- **Video vertical**: los MOV de móvil suelen venir con `rotation=90` en metadata; ffmpeg autorrota. Extraer con `scale=1080:1920` y componer en vertical, nunca forzar 16:9 (deforma).
- **Análisis de escenas**: extraer frames espaciados con `-ss <t> -frames:v 1` y analizarlos con visión LLM para mapear acciones a timestamps — validado, funciona bien.
- **Remotion**: `CameraMotionBlur`/`Trail` NO deben envolver `OffthreadVideo` (refetch sub-frame falla); `random()` siempre sembrado; `loadFont()` a nivel de módulo con weights/subsets limitados; `visualizeAudio` requiere null-guard y numberOfSamples potencia de 2; TransitionSeries: duración total = Σescenas − Σtransiciones.
- **Render local**: ~4–7 min por 1200 frames 1080×1920; los renders fallan con errores confusos ("Failed to fetch", 500) cuando el **disco está lleno** — C: anda ~99% ocupado, verificar espacio antes de renderizar.

## Convenciones
- Commits en español, mensaje descriptivo de fase/módulo.
- No comitear media (`.gitignore` ya lo excluye); secretos solo en `.env` (plantilla en `.env.example`).
