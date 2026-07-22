# Riesgos y mitigaciones

## Copyright (el mayor riesgo del formato movie-recap)
El formato usa material con derechos de autor.
- **YouTube:** Content ID típicamente desmonetiza o reclama; rara vez elimina si el contenido es transformativo.
- **TikTok/IG:** más laxos, pero pueden silenciar audio o reducir alcance.

**Mitigaciones:**
- Narración transformativa (crítica/resumen, nunca re-subida directa).
- Clips cortos y muy editados (cortes, zooms, overlays, subtítulos).
- Pipeline agnóstico al nicho: formatos alternativos con material propio o licenciado listos para pivotar.

## ToS multi-cuenta
- ✅ Crecer varias cuentas propias con contenido **diferenciado** por cuenta/nicho.
- ❌ Redes de cuentas coordinadas con contenido duplicado/spam: todas las plataformas lo detectan → baneos en cadena.

El diseño apunta a pocas cuentas con contenido diferenciado, no a granja de spam.

## Dependencia del intermediario de publicación
El publicador debe ser un módulo con interfaz propia — `publish(video, meta, red)` — para poder cambiar de proveedor si cae el servicio o cambian los precios.

## Automatización total
Nunca publicar sin aprobación humana (botón en Telegram). Es un tap y elimina el riesgo de publicar contenido problemático en masa.

## Infraestructura local
- El render corre local: requiere espacio en disco (C: actualmente ~99% lleno — resolver antes de Fase 1).
- Telegram bot API limita envío de video a 50 MB → previews comprimidos.
