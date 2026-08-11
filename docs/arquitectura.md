# Arquitectura de ViralFarm

> **Documento canónico.** Describe la arquitectura **objetivo** del sistema, acordada el
> 2026-08-05. Sustituye a la descripción de arquitectura del `README.md`, que documenta la
> implementación de la Fase 1 en TypeScript — hoy funcional y en proceso de ser reemplazada.
>
> Orden de lectura para quien llega nuevo: este documento → `decisiones.md` → `riesgos.md`.

---

## 1. Qué es el sistema

Una herramienta que **decide qué contenido producir y lo produce**, en formato vertical para
TikTok, a partir de material de video existente.

El producto de hoy son **series de episodios** a partir de películas: la película se parte en
entregas de 120-360 s que se publican en orden, cada una con recap narrado, arco propio y
cierre en tensión. El pipeline es agnóstico al nicho por diseño.

El objetivo declarado no es automatizar edición: es **tomar decisiones informadas** sobre qué
material tiene recorrido, qué fragmentos merecen producción y qué guion funciona — y ejecutar
solo lo que pasa esos filtros.

---

## 2. De dónde venimos y hacia dónde vamos

**Estado actual (Fase 1, TypeScript).** Un pipeline lineal de 7 pasos que funciona end-to-end:
ingesta → transcripción → selección de episodios → guion → TTS → montaje → render. Artefactos
JSON validados con Zod en `media/<videoId>/`, idempotencia por existencia de archivo, Remotion
para subtítulos y plantilla.

**Sus dos limitaciones de fondo:**

1. **La IA automatiza, no decide.** Una llamada para partir la película, una por episodio para
   el guion, y lo que salga se produce. No hay evaluación previa, ni alternativas, ni crítica,
   ni criterio sobre qué material merece el esfuerzo.
2. **El sistema es ciego a la imagen y al audio.** El LLM solo ve texto: diálogo transcrito con
   timestamps y marcas de silencio. No sabe qué ocurre en pantalla ni cómo suena.

**Hacia dónde vamos.** Reescritura completa en **Python**, con tres subsistemas en vez de un
pipeline, y capas de percepción y refinamiento que hoy no existen.

---

## 3. Principios de diseño

Los que ya regían y se conservan:

- **El bot propone, el humano aprueba.** Nunca se publica sin aprobación explícita.
- **El LLM propone, el código verifica y repara.** Las invariantes de negocio (recap,
  numeración, CTA, cobertura, duraciones) las impone el código, no el prompt. Un modelo puede
  ignorar una instrucción; una validación, no.
- **El artefacto es la interfaz.** Los pasos se comunican por archivos con esquema, validados
  al escribir y al leer. De ahí sale la reanudabilidad.
- **Idempotencia por artefacto.** Reejecutar retoma donde se quedó; `--force` rehace.
- **Fallar en el borde, no a mitad de un render.** Un artefacto corrupto o un disco lleno se
  detectan antes de gastar minutos.

Los que se añaden ahora:

- **Cada capa filtra antes de que la siguiente gaste.** Lo barato y determinista va primero;
  el LLM solo donde las señales indican que hay algo; la producción cara solo sobre lo que
  superó el scoring.
- **Toda decisión deja evidencia.** Score desglosado, versión de prompt, modelo y parámetros
  se persisten. Sin esa historia no hay forma de atribuir un resultado ni de mejorar.
- **El dominio es puro.** La lógica de negocio no toca disco, red ni configuración: se testea
  sin ffmpeg, sin claves de API y sin archivos.
- **Un solo lenguaje.** Python en todo el sistema. (Ver §9.)

---

## 4. Visión de sistema: tres subsistemas

```
╔═══════════════════════════════════════════════════════════════════════════╗
║  A · RADAR — qué producir           reloj propio: diario / semanal        ║
║     fuentes externas → señales → oportunidades puntuadas                  ║
║     salida: backlog priorizado                                            ║
╚═══════════════════════════════════════════════════════════════════════════╝
                                  │  oportunidad aprobada
                                  ▼
╔═══════════════════════════════════════════════════════════════════════════╗
║  B · PRODUCCIÓN — cómo producirlo   se dispara por video                  ║
║     percepción → comprensión → decisión → generación+crítica → montaje    ║
║     salida: episodios listos para aprobación                              ║
╚═══════════════════════════════════════════════════════════════════════════╝
                                  │  preview
                                  ▼
╔═══════════════════════════════════════════════════════════════════════════╗
║  C · CONTROL — aprobar y publicar   humano en el bucle                    ║
║     preview → aprobación → publicación multi-red → registro de resultado  ║
╚═══════════════════════════════════════════════════════════════════════════╝
```

Los tres se comunican por **estado persistido**, nunca por llamadas directas. El Radar puede
estar caído y la Producción sigue operativa desde la CLI; es la misma propiedad que ya se
exigía a n8n en la Fase 2.

---

## 5. Subsistema A — Radar

### 5.1 Qué resuelve

Hoy la entrada del sistema es "un mp4 que yo elijo". El Radar la invierte: la entrada pasa a
ser **una oportunidad detectada**, y el material es consecuencia de esa decisión.

### 5.2 La estrategia: catálogo olvidado, no tendencia

Decisión del 2026-08-05: el Radar **no busca contenido en tendencia**. Busca la brecha entre
calidad histórica y atención actual.

> Una película que fue buena, que la gente valoró en su momento, y que hoy nadie mira —
> para una audiencia que ni había nacido cuando se estrenó — es contenido *nuevo* con calidad
> *ya validada*.

Razones, en orden de peso:

1. **Producto.** Saturación casi nula (nadie hace recaps de un thriller de 2003 de presupuesto
   medio), calidad ya validada, catálogo prácticamente infinito y sin prisa de publicación. No
   se compite con los mil canales que suben el recap del estreno del viernes.
2. **Riesgo.** Menor vigilancia activa, menor interés comercial vivo, y mucho catálogo antiguo
   que **nunca se registró en Content ID** porque los derechos cambiaron de manos o el estudio
   desapareció.

**Precisión importante:** la antigüedad **no** cambia el estatus legal — el copyright no expira
porque el público se olvide, y Content ID es automático y no sabe qué año es. El eje real no es
"antigua" sino **huérfana o desatendida**: una película de 1999 de un estudio grande sigue
siendo alto riesgo; una de 2011 de una distribuidora que ya no existe es bajo riesgo. Ver
`riesgos.md`.

### 5.3 Fórmula de oportunidad

```
oportunidad = calidad_histórica × olvido_actual × (1 − saturación) × factibilidad × (1 − riesgo)
```

Score **desglosado y auditable**, nunca un número opaco: cada componente se persiste por
separado para poder inspeccionarlo y recalibrarlo.

| Señal | Medición | Qué se busca |
|---|---|---|
| **Calidad histórica** | rating de TMDB **y nº de votos** | Nota alta con volumen real de votos |
| **Olvido actual** | pageviews de Wikipedia hoy vs. su media histórica | **Rating alto + atención baja = la brecha.** Es el corazón del scoring |
| **Brecha generacional** | año de estreno vs. edad de la audiencia objetivo | Estrenada antes de que el espectador tuviera uso de razón |
| **Saturación** | recaps del título en YouTube: cuántos y con qué views | Pocos, o muchos pero malos y antiguos |
| **Riesgo** | estudio/distribuidora, si sigue viva, si la franquicia está activa | Evitar catálogo vigilado |
| **Orfandad de streaming** | *watch providers* de TMDB (vía JustWatch) | **Doble premio:** menos vigilancia comercial *y* el espectador no puede verla en ningún sitio, así que el recap es su único acceso |

### 5.4 Fuentes

| Fuente | Aporta | Estado |
|---|---|---|
| **TMDB API** | popularidad, rating, votos, año, géneros, watch providers | Oficial, gratuita, estable. **Columna vertebral** |
| **Wikipedia Pageviews API** | atención pública diaria por título e idioma | Oficial, gratuita, sin auth. Mide *olvido* y *momentum* |
| **YouTube Data API** | recaps existentes con views reales | Oficial, con cuota. Mide **saturación** |
| **TikTok Creative Center** | hashtags, sonidos y formatos en tendencia | Público; **verificar** forma estable de consulta |
| **Google Trends** | interés de búsqueda relativo | No oficial en Python, frágil. Contrastar, no depender |
| **Reddit API** | ángulos que interesan, señal cualitativa | Oficial |
| **Archive.org** | cine en **dominio público** | Veta de riesgo cero (ver §5.5) |

Reparto de responsabilidades: **TMDB y Wikipedia miden demanda y olvido · YouTube mide
saturación · TikTok Creative Center mide formato.** Ninguna sirve por separado.

Scrapers no oficiales de TikTok: descartados. Frágiles y contra ToS.

### 5.5 Veta paralela: dominio público

Categoría propia en el backlog. Archive.org tiene miles de películas legalmente libres,
incluidos clásicos cuyo copyright caducó por no renovarse. Riesgo cero y material ideal para
**validar pipeline y formato antes de tocar nada con derechos**. No es donde está el volumen de
audiencia, pero es donde se puede fallar gratis.

### 5.6 Recolección desde ya

Las series temporales solo valen si tienen historia. TMDB y Wikipedia son baratos de consultar:
un job diario que guarde snapshots **desde hoy** vale mucho más dentro de tres meses que
empezar a mirar entonces. Es lo único del Radar que conviene arrancar antes de tiempo.

---

## 6. Subsistema B — Producción

### 6.1 Las cinco capas

```
┌───────────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────┐  ┌─────────┐
│ 1 PERCEPCIÓN  │─►│ 2 COMPRENSIÓN│─►│ 3 DECISIÓN │─►│ 4 GENERA │─►│ 5 MONTA │
│ señales       │  │ eventos      │  │ candidatos │  │ + CRÍTICA│  │ y rinde │
│ objetivas     │  │ narrativos   │  │ + scoring  │  │ (bucle)  │  │         │
└───────────────┘  └──────────────┘  └────────────┘  └──────────┘  └─────────┘
  sin IA, barato,    LLM multimodal    genera N,       guion →       ffmpeg +
  determinista       SOLO donde las    puntúa,         crítico →     ASS
                     señales indican   descarta antes  revisión
                     que pasa algo     de gastar
```

**Capa 1 · Percepción — señales objetivas, sin IA.** Análisis de las trazas de audio y video:
energía RMS por ventana, silencios, ratio música/habla, picos de loudness (`ebur128`), cambios
de plano (ya implementado), densidad de movimiento, luminancia. Determinista, barato y
reproducible. Dice **dónde pasa algo** sin gastar un token. Hoy esta información no existe y el
LLM tiene que inferir intensidad leyendo diálogo.

**Capa 2 · Comprensión — visión dirigida, no muestreo ciego.** Un frame cada 10 s de una
película de 90 minutos son 540 imágenes y un coste absurdo. Frames **donde la capa 1 indica
evento** — pico de audio, corte de plano tras silencio largo, cambio de energía — son ~60
imágenes bien elegidas. Mismo dinero, mucha más señal. Es la primera decisión inteligente real
del sistema. Técnica ya validada en el proyecto hermano `my-video`.

Salida: **línea de tiempo multimodal** que fusiona diálogo, acciones y silencios en una
secuencia ordenada. Es el nuevo contrato de entrada de la capa 3.

**Capa 3 · Decisión — candidatos y scoring.** El paso de selección genera **más episodios de
los que se van a producir** y los puntúa con un score **desglosado**: densidad de eventos,
fuerza del cierre en tensión, autonomía narrativa, cobertura de copyright, calidad de los
cortes. No un `puntuacion: 8` que el modelo se inventa, sino componentes inspeccionables. Solo
los mejores pasan a producción.

Se persiste **lo que el sistema consideró** (`candidatos.json`) separado de **lo que eligió
producir** (`serie.json`). Esa separación es la que hace auditable la decisión.

**Capa 4 · Generación con refinamiento.** El guion pasa por un crítico con rúbrica explícita
—¿el hook promete algo concreto? ¿el cierre abre tensión o la resuelve? ¿la narración tapa la
escena clave?— y una iteración de revisión acotada. Es lo que más sube la calidad por token
gastado. Complementa las reparaciones mecánicas que ya hace el código.

**Capa 5 · Montaje y render.** Sin cambios conceptuales respecto a la Fase 1, salvo la
sustitución de Remotion (ver §9.2).

### 6.2 El pipeline, paso a paso

```
 video
   │
 [1] ingesta ────────────── ffprobe ─────────────────► fuente.json
   │   videoId = slug(nombre) + sha1(ruta:tamaño)[0..8]
   ▼
 [2] transcripción ──────── faster-whisper (in-process) ─► transcripcion.json
   │   timestamps por palabra: base de subtítulos y de cortes en frontera de frase
   ▼
 [3] percepción ─────────── ffmpeg + librosa (sin IA) ──► senales.json
   │   energía, silencios, música/habla, cortes de plano, movimiento
   ▼
 [4] comprensión ────────── frames dirigidos → LLM visión ─► vision.json
   │   qué ocurre en pantalla, con timestamps
   ▼
 [5] línea de tiempo ────── fusión determinista ────────► timeline.json
   │   diálogo + acciones + silencios en una sola secuencia
   ▼
 [6] candidatos ─────────── LLM propone N, código puntúa ─► candidatos.json
   │   scoring desglosado
   ▼
 [7] serie ──────────────── selección + reparación ─────► serie.json
   │   invariantes duras: ≥2 episodios · 120-360 s · sin solapes · numeración
   │   cobertura ≤ 60 % del fuente (error duro, copyright)
   ▼
 [8] guion ──────────────── LLM + crítico + revisión ───► ep/<n>/guion.json
   │   ⚠ CADENA DEPENDIENTE: el episodio n necesita resumen y cliffhanger de n-1.
   │      No paralelizable. Regenerar uno suelto desincroniza los recaps siguientes.
   │   el recap de 8 s y la numeración del caption los inserta el CÓDIGO
   │   narración entre 40 % y 65 % del episodio (aviso)
   ▼
 [9] voz ────────────────── edge-tts, concurrente ──────► ep/<n>/voz/*.mp3 + voz.json
   │   si no cabe en su tramo: atempo hasta 1.15×
   ▼
[10] montaje ───────────── ffmpeg, un solo pase ───────► ep/<n>/base.mp4
   │   recorte + 1080×1920 + ducking (−18 dB) + loudnorm −14 LUFS
   │   CHECKPOINT: aquí se valida lo más frágil (la mezcla) sin esperar al render
   ▼
[11] subtitulado ───────── .ass generado en Python + ffmpeg ─► final.mp4 + preview.mp4
       hook, chapa n/N y karaoke palabra a palabra
```

Los pasos 3, 4 y 6 no existen hoy. El 5 existe implícito dentro del prompt de selección y pasa
a ser artefacto propio: es lo que permite añadir percepción y visión **sin tocar nada aguas
abajo**.

### 6.3 Concurrencia

| Paso | Modo | Por qué |
|---|---|---|
| voz (TTS) | **concurrente** | ~10-15 tramos × N episodios; hoy son 100+ subprocesos en serie |
| montaje | **concurrente**, acotado | limitado por CPU y disco |
| percepción, visión | **concurrente** | ventanas y frames independientes |
| **guion** | **secuencial obligatorio** | cadena de recaps y cliffhangers |
| render | acotado | limitado por CPU |

---

## 7. Subsistema C — Control

Aprobación humana, publicación multi-red y registro del resultado. Máquina de estados del
video:

```
idea → analizado → guionizado → montado → preview → aprobado → publicado → medido
                                             └──────► rechazado
```

El publicador es un módulo swapeable con interfaz propia: `publicar(video, meta, red)`. Cambiar
de intermediario no debe tocar nada más.

**La aprobación registra el motivo del rechazo.** Es la señal de calidad más rápida que tiene
el sistema: llega en horas, no en semanas, y es lo que alimenta el refinamiento de prompts a
corto plazo.

> Nota: el mecanismo concreto de control (n8n vs. servicio propio en FastAPI) es una **decisión
> abierta**. Ver §11. `n8n-workflows.md` describe la propuesta con n8n y sigue siendo válida
> como diseño de los flujos, sea cual sea el motor.

---

## 8. Estructura de código

```
viral-farm/
  pyproject.toml
  viralfarm/
    cli.py              Typer: ingesta, percibir, timeline, serie, guion, voz, montar,
                        subtitular, run, radar
    config.py           pydantic-settings — SIN efectos al importar
    contratos/          Pydantic v2, un módulo por artefacto
    dominio/            ── PURO: sin disco, sin red, sin config. Aquí viven los tests ──
      senales.py          agregación de trazas de audio/video a eventos
      timeline.py         fusión determinista de diálogo + acciones + silencios
      episodios.py        normalización, reparación, alineación de cortes, cobertura
      scoring.py          score desglosado de candidatos
      tramos.py           reparto narración/original, recorte a ritmo de habla
      subtitulos.py       pista de subtítulos desde guion + voz + transcripción
      ass.py              serialización a formato ASS
      ducking.py          expresión de volumen trapezoidal
      idiomas.py          catálogo de voz, ritmo y CTA por idioma
    prompts/            serie.py · guion.py · critico.py · vision.py
    adaptadores/        llm.py · vision.py · whisper.py · tts.py · ffmpeg.py ·
                        escenas.py · audio.py · proceso.py
    pasos/              orquestación fina: leer artefacto → dominio → escribir artefacto
    radar/
      fuentes/            tmdb.py · wikipedia.py · youtube.py · archive.py · trends.py
      dominio/            scoring de oportunidad (puro)
      backlog.py
    estado/             repositorio (filesystem hoy, Postgres después) ·
                        máquina de estados · registro de decisiones
  tests/
  workspace/
    entrada/            los mp4 fuente
    trabajo/<videoId>/  artefactos de producción
    cache-llm/<videoId>/ respuestas del LLM, **con videoId** en la clave
    radar/              snapshots de señales externas (series temporales)
```

**Dos reglas que sostienen la estructura:**

1. **El dominio no importa `config`.** Así se testea sin ffmpeg, sin claves y sin archivos.
2. **Los pasos no saben quién los invoca** — CLI, worker o API. Reciben tipos de dominio, no
   tipos de la interfaz. (En la Fase 1 el tipo de opciones del CLI llegaba hasta el pipeline.)

---

## 9. Stack y decisiones técnicas

### 9.1 Python en todo el sistema

`uv` (entorno y dependencias) · **Pydantic v2** (contratos) · **Typer** (CLI) · `anthropic` ·
`faster-whisper` · `edge-tts` · `librosa` (trazas de audio) · ffmpeg por `subprocess` ·
`pytest` + `ruff` + `mypy`. **Sin Node, sin npm.**

Razones: es el lenguaje que el autor domina y mantendrá — y el código que más se toca son los
prompts y las reglas del formato; la transcripción y el TTS **ya eran Python** invocados por
subproceso, y pasan a ser llamadas directas; y el ecosistema de análisis de audio y visión vive
en Python.

Equivalencias: Zod → Pydantic · `parseArgs` → Typer · `spawn` → `subprocess` · las respuestas
estructuradas del LLM se validan igual, contra el mismo esquema que el artefacto de disco.

### 9.2 Remotion se elimina: subtítulos por ASS/libass

Remotion hacía tres cosas sobre un `base.mp4` que ffmpeg ya dejaba montado: hook animado, chapa
`n/N` y subtítulos karaoke.

**ASS es el formato que se inventó para karaoke**: resaltado por palabra, color, escala
(`\fscx`/`\fscy`), posición, fade y transiciones temporizadas (`\t`). Se genera desde Python
como texto plano y se quema con `ffmpeg -vf subtitles=`.

Beneficios: desaparece Node del repo y el render deja de ser frame a frame en un navegador.

**Medido el 2026-08-06** sobre los dos episodios de `pelicula-prueba` (697 s de vídeo, mismos
`base.mp4` de entrada):

| | Remotion | ASS/libass |
|---|---|---|
| Tiempo total | **51,3 min** | **6,0 min** (8,6× más rápido) |
| Por episodio | 28,9 y 21,6 min | 2,9 y 3,1 min |
| Velocidad | 0,2× tiempo real | **2,0× tiempo real** |
| Tamaño de salida | 242 MB | 158 MB (−35 %) |

La estimación previa (1-3 min por episodio) resultó correcta. El resultado visual es
equivalente: hook, chapa `n / N` y karaoke con color distinto según el origen de la palabra.

Coste asumido: se pierde Remotion Studio (preview interactiva) y la sinergia de código con el
proyecto hermano `my-video`, que queda como referencia conceptual. Si en el futuro se quieren
motion graphics ricos —b-roll animado, transiciones, gráficos sobre el video— ASS se queda
corto y habría que reintroducir un motor de composición. **El paso de subtitulado queda detrás
de una interfaz para que ese cambio no toque el resto del pipeline.**

### 9.3 Fallos de la Fase 1 que la reescritura corrige

| # | Fallo | Corrección |
|---|---|---|
| 1 | Caché del LLM sin `videoId` en la clave: una segunda película reutilizaba el guion de la primera, y pasaba la validación de esquema | `cache-llm/<videoId>/` |
| 2 | Cero tests, con la lógica frágil (normalización, ducking, subtítulos) solo verificable renderizando | `dominio/` puro + `pytest` desde la fase 1 |
| 3 | Sin capa de estado: el estado era "qué archivos existen" | `estado/` con repositorio y máquina de estados |
| 4 | `config` resolvía ffmpeg al importarse: cualquier módulo exigía ffmpeg presente | `config.py` sin efectos al importar |
| 5 | El tipo de opciones del CLI llegaba hasta el pipeline | tipos de dominio en la frontera |
| 6 | Dominio, prompts, I/O y logs en el mismo archivo (606 y 553 líneas) | `dominio/` · `prompts/` · `adaptadores/` · `pasos/` |
| 7 | Todo secuencial, incluso lo paralelizable | ver §6.3 |
| 8 | Vocabulario desalineado: todo se llamaba *clip* cuando el producto son *episodios* | `serie.json`, `ep/<n>/`, `--episodio` |
| 9 | `media/` mezclaba entradas, trabajo y cachés, y era el `publicDir` de Remotion | `workspace/` con las tres separadas |

### 9.4 Compatibilidad de artefactos

Los artefactos de `media/pelicula-prueba-05-25-12e8a388/` —`fuente.json`, `transcripcion.json`,
`clips.json` y los `clips/<n>/guion.json` y `clips/<n>/narracion.json`— **validan contra los
contratos Pydantic**, verificado por `tests/test_contratos_golden.py`. `transcripcion.json` lo
hace sin conversión; los demás usan camelCase y pasan por `viralfarm/contratos/legado.py`.

Se usan como *golden files*: cada fase de la migración se verifica reproduciendo la salida del
TS, no contra criterio. Los tests se saltan solos si `media/` no está (no se versiona).

---

## 10. Roadmap

> **Estado al 2026-08-06:** fases 0 y 1 implementadas (contratos y dominio puro), más el
> adaptador de LLM y el de subtitulado ASS adelantados de las fases 2 y 4. El pipeline
> TypeScript sigue siendo el operativo hasta la fase 3.

| Fase | Contenido | Criterio de aceptación |
|---|---|---|
| **0** ✅ | Andamiaje: `pyproject`, ruff/mypy/pytest, `config` sin efectos al importar, contratos Pydantic + lectura de artefactos legado | Hecho el 2026-08-05: los artefactos existentes validan contra los esquemas nuevos |
| **1** ✅ | `dominio/`: episodios, tramos, subtítulos, ASS, ducking, idiomas, timeline | Hecho el 2026-08-05: 93 tests, mypy strict y ruff en verde |
| **2** | `adaptadores/` (ffmpeg, whisper, tts, llm con caché por videoId) | Transcripción y voz equivalentes al TS |
| **3** | `pasos/` + CLI Typer — paridad funcional con la Fase 1 | `run` end-to-end produce la misma serie |
| **4** ✅ | Subtitulado ASS, Remotion fuera | Validado el 2026-08-06: 8,6× más rápido que Remotion, salida equivalente (ver §9.2) |
| **5** | Borrar `src/`, `remotion/`, `package.json`, `node_modules` | El repo es 100 % Python |
| **6** | Capa 1: percepción (trazas de audio y video) | `senales.json` marca los picos reales del material |
| **7** | Capas 2 y 5: visión dirigida y `timeline.json` | El guion menciona acciones ausentes del diálogo |
| **8** | Capa 3: candidatos y scoring desglosado | Se producen solo los mejores de N propuestos |
| **9** | Capa 4: crítico y revisión del guion | Mejora medible contra la rúbrica |
| **10** | Radar: TMDB + Wikipedia + YouTube, backlog priorizado | Propone material que supera el filtro de olvido y saturación |
| **11** | Control: aprobación, publicación, registro | Ciclo completo con humano en el bucle |

**Recolección del Radar en paralelo desde la fase 0**: snapshots diarios de TMDB y Wikipedia,
aunque no se consuman todavía (§5.6).

Fases 1 y 4 son las que llevan el trabajo real; 0, 2, 3 y 5 son mecánicas.

---

## 11. Decisiones abiertas

| Decisión | Por qué importa |
|---|---|
| **Motor de control: n8n o servicio propio en FastAPI** | `n8n-workflows.md` está diseñado sobre n8n y la instancia local se eliminó el 2026-07-31. Con todo el sistema en Python, un servicio propio deja de ser más caro que n8n |
| **Alcance del Radar: solo cine o multi-nicho** | TMDB solo sirve para películas. Si aspira a cualquier video, hace falta una capa de fuentes por nicho — se puede diseñar con esa forma aunque solo se implemente cine |
| **Origen del material** | El Radar puede señalar la oportunidad, pero sin forma de conseguir el archivo la recomendación es teórica |
| **¿Herramienta propia o producto?** | Si es propia, el scoring puede ser opinado y el juez final es el autor. Si aspira a producto, tiene que ser explicable y configurable desde el principio |
| **Intermediario de publicación** | Upload-Post vs. Blotato vs. Metricool (pendiente desde la Fase 0) |
| **Presupuesto de IA** | Las capas 2, 3 y 4 añaden llamadas; la matriz de costos de `decisiones.md` necesita recalcularse |
```
