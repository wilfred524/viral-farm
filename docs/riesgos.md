# Riesgos y mitigaciones

## Copyright (el mayor riesgo del formato movie-recap)
El formato usa material con derechos de autor.
- **YouTube:** Content ID típicamente desmonetiza o reclama; rara vez elimina si el contenido es transformativo.
- **TikTok/IG:** más laxos, pero pueden silenciar audio o reducir alcance.

**Mitigaciones:**
- Narración transformativa (crítica/resumen, nunca re-subida directa).
- Piezas muy editadas (cortes, zooms, overlays, subtítulos).
- Pipeline agnóstico al nicho: formatos alternativos con material propio o licenciado listos para pivotar.

### El formato serie sube la exposición (2026-07-31)

Episodios de 2 a 6 minutos, contiguos y en orden cronológico, son un patrón mucho más fácil de
detectar para Content ID que los clips sueltos de 20-60 s del formato anterior, y debilitan el
argumento de uso transformativo. Dos límites, aplicados **por código** y no por criterio:

| Límite | Dónde se aplica | Qué pasa si se incumple |
|---|---|---|
| **Cobertura ≤ 60 %** del fuente entre todos los episodios | `normalizarEpisodios()` en `src/pasos/clips.ts` (`COBERTURA_MAX`) | El paso **falla**: hay que dejar más huecos o reducir `--n` |
| **Narración ≥ 40 %** de cada episodio (y ≤ 65 %, para que la película respire) | `generarGuion()` en `src/pasos/guion.ts` (`NARRACION_MIN`/`NARRACION_MAX`) | Aviso en el log; queda registrado en el guion para revisarlo |

La cobertura efectiva se guarda en `clips.json` (`serie.cobertura`), así que es auditable a
posteriori sin volver a ejecutar nada.

Fuera del código: el formato serie es para material sin un estudio grande detrás. Con una
película de catálogo mayor, la probabilidad de reclamación es alta por muchos huecos que se
dejen.

### Selección de material: catálogo olvidado (2026-08-05)

Lo anterior deja de ser una advertencia genérica y pasa a ser **criterio de selección con
señales medibles**, aplicado por el Radar (ver `arquitectura.md` §5).

**Qué NO cambia con la antigüedad del material:**

- El copyright **no expira porque el público se olvide**. Una película de 1998 está tan
  protegida como una de 2025 (EE.UU.: ~95 años desde la publicación; Latinoamérica: vida del
  autor + 80).
- **Content ID es automático y no sabe qué año es.** Si el titular registró la obra, salta
  igual con una película de 1997 que con un estreno.

**Qué SÍ cambia, y es donde está el margen real:**

| Factor | Efecto |
|---|---|
| Vigilancia activa | Los equipos legales persiguen estrenos y franquicias vivas, no catálogo de hace 20 años |
| Registro en Content ID | Mucho catálogo antiguo **nunca se registró**: estudios quebrados, fusionados o con derechos vendidos varias veces |
| Interés comercial vivo | Si la obra no genera ingresos hoy, reclamar es coste sin retorno |
| Daño económico | Cercano a cero, que es lo que sostiene el argumento de uso transformativo |

**El eje no es "antigua" sino "huérfana o desatendida".** Una película de 1999 de un estudio
grande es antigua y sigue siendo altísimo riesgo; una de 2011 de una distribuidora que ya no
existe es reciente y es bajo riesgo.

**Señal de riesgo más útil: orfandad de streaming.** Que un título no esté en ninguna
plataforma (comprobable con los *watch providers* de TMDB) indica a la vez menor vigilancia
comercial y mayor valor para el espectador, que no tiene otra forma de acceder a la historia.

**Veta de riesgo cero: dominio público.** Archive.org tiene miles de películas legalmente
libres, incluidos clásicos cuyo copyright caducó por no renovarse. Es donde conviene validar
pipeline y formato antes de tocar material con derechos.

Nada de esto elimina el riesgo: monetizar obra ajena sigue siendo territorio gris. Lo que hace
es convertir una intuición en parámetros que el sistema puede puntuar y registrar.

## ToS multi-cuenta
- ✅ Crecer varias cuentas propias con contenido **diferenciado** por cuenta/nicho.
- ❌ Redes de cuentas coordinadas con contenido duplicado/spam: todas las plataformas lo detectan → baneos en cadena.

El diseño apunta a pocas cuentas con contenido diferenciado, no a granja de spam.

## Dependencia del intermediario de publicación
El publicador debe ser un módulo con interfaz propia — `publish(video, meta, red)` — para poder cambiar de proveedor si cae el servicio o cambian los precios.

## Automatización total
Nunca publicar sin aprobación humana (botón en Telegram). Es un tap y elimina el riesgo de publicar contenido problemático en masa.

## Infraestructura local
- El render corre local: requiere espacio en disco (C: con ~11 GB libres tras la limpieza de 2026-07-30).
- Telegram bot API limita envío de video a 50 MB → previews comprimidos. Medido: un episodio de
  130 s da un `preview.mp4` de 6,6 MB, así que uno de 360 s ronda los 18 MB. Sigue habiendo margen.
- Los episodios largos multiplican el tiempo de render (~18 min por episodio de 4,5 min). Antes de
  lanzar una serie entera, `verificarEspacioParaSerie()` estima el disco necesario y aborta al
  principio en vez de a mitad del lote.
