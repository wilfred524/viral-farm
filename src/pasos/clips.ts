/**
 * Paso 3 — De la película a la lista de piezas. Dos formatos:
 *
 * - `serie` (por defecto): la película se convierte en episodios de varios minutos que se
 *   publican en orden. Cada uno cierra el arco que abre pero deja una tensión nueva al final,
 *   que resuelve el siguiente. Es el formato que sostiene una cuenta: el espectador vuelve.
 * - `virales`: el comportamiento original, fragmentos sueltos de 20-60 s (Módulo 02 de la
 *   propuesta técnica). Se conserva como alternativa.
 *
 * En ambos casos el LLM propone y el código verifica. La diferencia está en qué se hace con lo
 * que no cuadra: en `virales` se descarta, en `serie` se REPARA — descartar un episodio rompe
 * la cadena de recaps y cliffhangers de todos los que vienen detrás.
 */

import { z } from "zod";
import { config } from "../config.js";
import {
  ClipsSchema,
  FuenteSchema,
  TranscripcionSchema,
  type Alineacion,
  type Clip,
  type Clips,
  type Fuente,
  type Transcripcion,
} from "../tipos.js";
import { pedirEstructurado } from "../lib/llm.js";
import { escribirJson, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";
import { resolverIdioma } from "../lib/idiomas.js";
import { detectarCortes } from "../lib/escenas.js";

// --- formato virales (legado) ---
const VIRAL_MIN = 20;
const VIRAL_MAX = 60;

// --- formato serie ---
const DURACION_MIN = 120;
const DURACION_OBJETIVO = 270;
const DURACION_MAX = 360;
/** Segundos entre el desenlace y el final del episodio: ahí va el cierre en tensión. */
const COLA_MINIMA = 10;
/** Hueco sin habla que se marca en el prompt para que el LLM no sea ciego a lo no dialogado. */
const SILENCIO_NOTABLE = 15;
/**
 * Tope de fracción del fuente que pueden cubrir los episodios. Trozos contiguos y en orden que
 * cubren casi toda la película es justo el patrón que detectan los sistemas de copyright, y
 * debilita el argumento de uso transformativo. Ver docs/riesgos.md.
 */
const COBERTURA_MAX = 0.6;

// ---------------------------------------------------------------------------
// Utilidades comunes
// ---------------------------------------------------------------------------

/** Lleva un instante al comienzo/fin de segmento más cercano para no cortar frases. */
function ajustarAFrontera(
  tiempo: number,
  transcripcion: Transcripcion,
  extremo: "inicio" | "fin",
  tolerancia = 2,
): number {
  const candidatos = transcripcion.segmentos.map((s) => (extremo === "inicio" ? s.inicio : s.fin));
  let mejor = tiempo;
  let distancia = Infinity;
  for (const candidato of candidatos) {
    const d = Math.abs(candidato - tiempo);
    if (d < distancia && d <= tolerancia) {
      distancia = d;
      mejor = candidato;
    }
  }
  return mejor;
}

/** true si el instante cae dentro de una palabra: cortar ahí parte el habla por la mitad. */
function parteUnaPalabra(tiempo: number, transcripcion: Transcripcion): boolean {
  for (const segmento of transcripcion.segmentos) {
    if (segmento.fin < tiempo || segmento.inicio > tiempo) continue;
    for (const palabra of segmento.palabras) {
      if (tiempo > palabra.inicio && tiempo < palabra.fin) return true;
    }
  }
  return false;
}

/** Fronteras de segmento ordenadas, para reparar duraciones. */
function fronteras(transcripcion: Transcripcion, extremo: "inicio" | "fin"): number[] {
  return transcripcion.segmentos
    .map((s) => (extremo === "inicio" ? s.inicio : s.fin))
    .sort((a, b) => a - b);
}

// ---------------------------------------------------------------------------
// Formato virales (legado, sin cambios de comportamiento)
// ---------------------------------------------------------------------------

const RespuestaViralesSchema = z.object({
  clips: z.array(
    z.object({
      inicio: z.number().describe("Segundo de inicio del clip en el video fuente"),
      fin: z.number().describe("Segundo de fin del clip en el video fuente"),
      titulo: z.string().describe("Título corto y con gancho para el clip"),
      razon: z.string().describe("Por qué este fragmento retiene la atención"),
      puntuacion: z.number().describe("Potencial viral de 0 a 10"),
    }),
  ),
});

const SISTEMA_VIRALES = `Eres un editor de contenido vertical (TikTok, Reels, Shorts) especializado en
detectar los momentos de un video largo con más potencial de retención.

Buscas fragmentos que:
- Abren con un gancho en los primeros 1.5 segundos (pregunta, afirmación fuerte, tensión).
- Se entienden solos, sin haber visto el resto del video.
- Tienen un arco: tensión y resolución o giro final.
- Empiezan y terminan en frontera de frase, nunca a mitad de palabra.

Evitas: introducciones, agradecimientos, transiciones administrativas y tramos sin habla.`;

function normalizarVirales(
  propuestos: z.infer<typeof RespuestaViralesSchema>["clips"],
  transcripcion: Transcripcion,
  duracionFuente: number,
): Clip[] {
  const validos = propuestos
    .map((c) => ({
      ...c,
      inicio: Math.max(0, ajustarAFrontera(c.inicio, transcripcion, "inicio")),
      fin: Math.min(duracionFuente, ajustarAFrontera(c.fin, transcripcion, "fin")),
    }))
    .filter((c) => {
      const duracion = c.fin - c.inicio;
      return duracion >= VIRAL_MIN * 0.75 && duracion <= VIRAL_MAX * 1.5;
    })
    .sort((a, b) => a.inicio - b.inicio);

  // Elimina solapes conservando el clip mejor puntuado de cada colisión.
  const sinSolapes: typeof validos = [];
  for (const clip of validos) {
    const previo = sinSolapes[sinSolapes.length - 1];
    if (previo && clip.inicio < previo.fin) {
      if (clip.puntuacion > previo.puntuacion) sinSolapes[sinSolapes.length - 1] = clip;
      continue;
    }
    sinSolapes.push(clip);
  }

  return sinSolapes.map((c, indice) => ({
    indice,
    inicio: c.inicio,
    fin: c.fin,
    titulo: c.titulo,
    razon: c.razon,
    puntuacion: Math.min(10, Math.max(0, c.puntuacion)),
  }));
}

async function seleccionarVirales(
  videoId: string,
  fuente: Fuente,
  transcripcion: Transcripcion,
  n: number,
  idiomaSalida: string | undefined,
): Promise<Clips> {
  const origen = resolverIdioma(transcripcion.idioma);
  const salida = resolverIdioma(idiomaSalida?.trim() || transcripcion.idioma);

  const prompt = `Video de ${fuente.duracion.toFixed(0)} segundos, hablado en ${origen.nombre}.
Transcripción con timestamps, en su idioma original:

${transcripcion.segmentos.map((s) => `[${s.inicio.toFixed(1)}–${s.fin.toFixed(1)}] ${s.texto}`).join("\n")}

Selecciona los ${n} fragmentos con más potencial viral. Cada uno debe durar entre
${VIRAL_MIN} y ${VIRAL_MAX} segundos, no solaparse con los demás y empezar y terminar
en frontera de frase (usa los timestamps de arriba). Ordénalos por potencial descendente.

Escribe el título y la razón de cada clip en ${salida.nombre}.`;

  const respuesta = await pedirEstructurado(RespuestaViralesSchema, {
    sistema: SISTEMA_VIRALES,
    prompt,
    etiqueta: "clips",
  });

  const clips = normalizarVirales(respuesta.clips, transcripcion, fuente.duracion).slice(0, n);
  if (clips.length === 0) {
    throw new Error(
      "Ningún clip propuesto superó la validación (duración o solapes). Revisa la transcripción.",
    );
  }
  if (clips.length < n) {
    console.warn(`· clips: se pedían ${n} pero solo ${clips.length} superaron la validación.`);
  }

  const resultado = await escribirJson(rutas.clips(videoId), ClipsSchema, {
    modelo: config.modeloLlm,
    formato: "virales",
    clips,
  });
  for (const clip of resultado.clips) {
    console.log(
      `  #${clip.indice} ${clip.inicio.toFixed(1)}–${clip.fin.toFixed(1)}s ` +
        `(${(clip.fin - clip.inicio).toFixed(0)}s, ${clip.puntuacion}/10) — ${clip.titulo}`,
    );
  }
  return resultado;
}

// ---------------------------------------------------------------------------
// Formato serie
// ---------------------------------------------------------------------------

const RespuestaSerieSchema = z.object({
  tituloSerie: z.string().describe("Título de la serie completa"),
  sinopsis: z.string().describe("Sinopsis de la serie en 2-3 frases"),
  episodios: z.array(
    z.object({
      inicio: z.number().describe("Segundo absoluto de inicio en el video fuente"),
      fin: z.number().describe("Segundo absoluto de fin en el video fuente"),
      titulo: z.string().describe("Título del episodio, con gancho, SIN el número de parte"),
      razon: z.string().describe("Por qué este tramo funciona como episodio autónomo"),
      cumbre: z.number().describe("Segundo ABSOLUTO del pico de tensión del episodio"),
      desenlace: z.number().describe("Segundo ABSOLUTO en que se cierra el arco abierto"),
      resumen: z
        .string()
        .describe("2-3 frases de lo que ocurre; base del recap del episodio siguiente"),
      cliffhanger: z.string().describe("La tensión que queda abierta al final, en una frase"),
      puntuacion: z.number().describe("0-10, cuánto engancha el episodio"),
    }),
  ),
});

const SISTEMA_SERIE = `Eres guionista de series verticales. Conviertes una película larga en una SERIE
de episodios que se publican en orden, uno por entrega, en TikTok.

El producto NO son "los mejores momentos": es una serie. Reglas del formato:

1. ORDEN CRONOLÓGICO ESTRICTO. El episodio 2 empieza después de donde terminó el 1. Nunca
   vuelves atrás, nunca reordenas, nunca repites material.
2. CADA EPISODIO ES UN RANGO CONTIGUO [inicio, fin] del material. Jamás saltas DENTRO de un
   episodio.
3. COBERTURA HÍBRIDA. ENTRE un episodio y el siguiente sí puede haber hueco: te saltas el
   material de relleno. Donde la acción es continua, encadenas sin hueco (el fin de uno es
   exactamente el inicio del siguiente). Decides según el material: ni fuerzas la cobertura
   total ni fabricas saltos artificiales. Nunca te saltas algo que haga incomprensible el
   episodio siguiente.
4. ARCO POR EPISODIO. Cada episodio tiene planteamiento, CUMBRE (máxima tensión) y DESENLACE
   que cierra lo que abrió. Puede contener varios sub-arcos, pero el espectador termina el
   episodio satisfecho, no estafado.
5. CIERRE EN TENSIÓN. Después del desenlace, en los últimos segundos, plantas una tensión NUEVA
   que NO resuelves: una aparición, una decisión pendiente, una revelación a medias. Esa
   tensión es lo primero que resuelve el episodio siguiente. Este es el motor de la serie.
6. CONTINUIDAD. El resumen de un episodio es la materia prima del recap del siguiente.
   Escríbelo pensando en alguien que no vio la entrega anterior.

Cortas siempre en frontera de frase de la transcripción, nunca a mitad de diálogo, y a ser
posible en un cambio de escena.

Evitas: créditos, logos de productora, y tramos largos sin acción ni diálogo (marcados como
«sin diálogo» en la transcripción) salvo que sean escena en sí: una persecución, un silencio
cargado, un montaje musical.`;

/**
 * Transcripción para el prompt, con los silencios marcados. Sin esto el LLM solo ve diálogo y
 * es ciego a la mitad no hablada de una película — justo donde suele estar el relleno que se
 * le pide detectar.
 */
function formatearConSilencios(transcripcion: Transcripcion, duracionFuente: number): string {
  const lineas: string[] = [];
  let anterior = 0;
  for (const s of transcripcion.segmentos) {
    const hueco = s.inicio - anterior;
    if (hueco >= SILENCIO_NOTABLE) {
      lineas.push(
        `[${anterior.toFixed(1)}–${s.inicio.toFixed(1)}] «sin diálogo · ${hueco.toFixed(0)} s»`,
      );
    }
    lineas.push(`[${s.inicio.toFixed(1)}–${s.fin.toFixed(1)}] ${s.texto}`);
    anterior = Math.max(anterior, s.fin);
  }
  const cola = duracionFuente - anterior;
  if (cola >= SILENCIO_NOTABLE) {
    lineas.push(
      `[${anterior.toFixed(1)}–${duracionFuente.toFixed(1)}] «sin diálogo · ${cola.toFixed(0)} s»`,
    );
  }
  return lineas.join("\n");
}

interface Episodio {
  inicio: number;
  fin: number;
  titulo: string;
  razon: string;
  cumbre: number;
  desenlace: number;
  resumen: string;
  cliffhanger: string;
  puntuacion: number;
  alineacion: { inicio: Alineacion; fin: Alineacion };
}

/**
 * Alinea una frontera a un cambio de plano, con fallback a frontera de frase. Un corte visual
 * que parte una palabra por la mitad es peor que no alinear, así que esos se descartan.
 */
function alinearCorte(
  tiempo: number,
  extremo: "inicio" | "fin",
  transcripcion: Transcripcion,
  cortesVisuales: number[],
  fps: number,
): { tiempo: number; modo: Alineacion } {
  for (const corte of cortesVisuales) {
    // En el fin se retrocede un frame: dejar el primer frame del plano siguiente pegado al
    // final del episodio se lee como un fallo de edición.
    const candidato = extremo === "inicio" ? corte : Math.max(0, corte - 1 / fps);
    if (parteUnaPalabra(candidato, transcripcion)) continue;
    return { tiempo: candidato, modo: "escena" };
  }

  const porFrase = ajustarAFrontera(tiempo, transcripcion, extremo);
  if (porFrase !== tiempo) return { tiempo: porFrase, modo: "frase" };
  return { tiempo, modo: "llm" };
}

/**
 * Fuerza las invariantes de la serie sobre lo que propuso el LLM: orden, contigüidad, duración
 * y arco. La política es REPARAR, no descartar: perder un episodio deja sin sentido el recap
 * del siguiente y el cliffhanger del anterior.
 */
function normalizarEpisodios(
  propuestos: Episodio[],
  transcripcion: Transcripcion,
  duracionFuente: number,
): { clips: Clip[]; cobertura: number } {
  const ordenados = [...propuestos]
    .filter((e) => e.fin > e.inicio)
    .sort((a, b) => a.inicio - b.inicio);

  const finales = fronteras(transcripcion, "fin");
  const reparados: Episodio[] = [];

  for (const [posicion, episodio] of ordenados.entries()) {
    const previo = reparados[reparados.length - 1];
    // Techo para estirar: donde empieza el siguiente propuesto, o el final del fuente.
    const techo = ordenados[posicion + 1]?.inicio ?? duracionFuente;

    // 1. Solape: se trunca el inicio contra el episodio anterior, nunca se elimina.
    let inicio = Math.max(0, episodio.inicio);
    if (previo && inicio < previo.fin) inicio = previo.fin;

    let fin = Math.min(duracionFuente, episodio.fin);

    // 2. Duración: recortar por arriba y estirar por abajo, siempre a frontera de frase.
    if (fin - inicio > DURACION_MAX) {
      const tope = inicio + DURACION_MAX;
      const candidatos = finales.filter((f) => f > inicio && f <= tope);
      fin = candidatos.length > 0 ? candidatos[candidatos.length - 1]! : tope;
    }
    if (fin - inicio < DURACION_MIN) {
      const minimo = inicio + DURACION_MIN;
      const limite = Math.min(duracionFuente, techo);
      const candidato = finales.find((f) => f >= minimo && f <= limite);
      const estirado = candidato ?? (minimo <= limite ? minimo : fin);
      if (estirado - inicio <= DURACION_MAX) fin = estirado;
    }

    // 3. Si sigue sin caber, fusionar con el anterior antes de rendirse.
    if (fin - inicio < DURACION_MIN) {
      if (previo && fin - previo.inicio <= DURACION_MAX) {
        console.warn(
          `  · episodio "${episodio.titulo}" (${(fin - inicio).toFixed(0)} s) fusionado con el anterior.`,
        );
        previo.fin = fin;
        previo.cliffhanger = episodio.cliffhanger;
        previo.resumen = `${previo.resumen} ${episodio.resumen}`.trim();
        previo.desenlace = episodio.desenlace;
        previo.cumbre = Math.max(previo.cumbre, episodio.cumbre);
        previo.alineacion.fin = episodio.alineacion.fin;
        continue;
      }
      console.warn(
        `  · episodio "${episodio.titulo}" descartado: ${(fin - inicio).toFixed(0)} s, ` +
          `no llega al mínimo de ${DURACION_MIN} s y no hay con quién fusionarlo.`,
      );
      continue;
    }

    reparados.push({ ...episodio, inicio, fin });
  }

  const clips: Clip[] = reparados.map((e, posicion) => {
    const duracion = e.fin - e.inicio;

    // 4. Arco a tiempos relativos, con reparación si el LLM lo situó fuera del episodio.
    let cumbre = e.cumbre - e.inicio;
    let desenlace = e.desenlace - e.inicio;
    const topeDesenlace = duracion - COLA_MINIMA;
    if (!(cumbre > 0 && cumbre < desenlace && desenlace <= topeDesenlace)) {
      cumbre = duracion * 0.62;
      desenlace = duracion * 0.85;
      console.warn(
        `  · episodio ${posicion + 1}: arco fuera de rango, recolocado en ` +
          `cumbre ${cumbre.toFixed(0)} s / desenlace ${desenlace.toFixed(0)} s.`,
      );
    }

    const anterior = reparados[posicion - 1];
    return {
      indice: posicion,
      inicio: e.inicio,
      fin: e.fin,
      titulo: e.titulo,
      razon: e.razon,
      puntuacion: Math.min(10, Math.max(0, e.puntuacion)),
      parte: posicion + 1,
      totalPartes: reparados.length,
      arco: { cumbre, desenlace },
      resumen: e.resumen,
      cliffhanger: e.cliffhanger,
      huecoAnterior: anterior ? Math.max(0, e.inicio - anterior.fin) : 0,
      alineacion: e.alineacion,
    };
  });

  // 5. Validaciones duras: un error aquí se propaga a horas de render.
  if (clips.length < 2) {
    throw new Error(
      `Una serie necesita al menos 2 episodios y solo sobrevivió ${clips.length}. ` +
        `Revisa la transcripción o usa --formato virales.`,
    );
  }
  for (const [i, c] of clips.entries()) {
    const duracion = c.fin - c.inicio;
    if (duracion < DURACION_MIN || duracion > DURACION_MAX) {
      throw new Error(
        `Episodio ${c.parte} dura ${duracion.toFixed(0)} s, fuera de [${DURACION_MIN}, ${DURACION_MAX}].`,
      );
    }
    if (c.inicio < 0 || c.fin > duracionFuente) {
      throw new Error(`Episodio ${c.parte} se sale del fuente (${c.inicio}–${c.fin}).`);
    }
    if (i > 0 && c.inicio < clips[i - 1]!.fin) {
      throw new Error(`Episodio ${c.parte} solapa con el anterior.`);
    }
    if (c.parte !== i + 1 || c.totalPartes !== clips.length) {
      throw new Error(`Numeración incorrecta en el episodio ${i + 1}.`);
    }
    if (i < clips.length - 1 && !c.cliffhanger?.trim()) {
      console.warn(`  · episodio ${c.parte} sin cliffhanger: la serie pierde tirón ahí.`);
    }
    if ((c.huecoAnterior ?? 0) > 300) {
      console.warn(
        `  · episodio ${c.parte}: salto de ${(c.huecoAnterior! / 60).toFixed(1)} min desde el ` +
          `anterior; el recap tendrá que cubrirlo.`,
      );
    }
  }

  const cubierto = clips.reduce((suma, c) => suma + (c.fin - c.inicio), 0);
  const cobertura = cubierto / duracionFuente;
  if (cobertura > COBERTURA_MAX) {
    throw new Error(
      `Los episodios cubren el ${(cobertura * 100).toFixed(0)} % de la película, por encima del ` +
        `${(COBERTURA_MAX * 100).toFixed(0)} % permitido. Reduce --n o deja más huecos entre ` +
        `episodios (ver docs/riesgos.md).`,
    );
  }

  return { clips, cobertura };
}

async function seleccionarSerie(
  videoId: string,
  fuente: Fuente,
  transcripcion: Transcripcion,
  n: number,
  idiomaSalida: string | undefined,
  sinEscenas: boolean,
): Promise<Clips> {
  const origen = resolverIdioma(transcripcion.idioma);
  const salida = resolverIdioma(idiomaSalida?.trim() || transcripcion.idioma);

  const prompt = `Película de ${fuente.duracion.toFixed(0)} segundos (${(fuente.duracion / 60).toFixed(0)} minutos),
hablada en ${origen.nombre}. Transcripción con timestamps absolutos del fuente; las líneas
«sin diálogo» marcan tramos sin habla:

${formatearConSilencios(transcripcion, fuente.duracion)}

Divide la película en una serie de episodios.

- Cada episodio dura entre ${DURACION_MIN} y ${DURACION_MAX} segundos (objetivo ${DURACION_OBJETIVO}).
- Como máximo ${n} episodios. Devuelve los que el material dé de sí: menos episodios buenos
  siempre es mejor que estirar la serie con relleno.
- Los episodios NO pueden cubrir más del ${(COBERTURA_MAX * 100).toFixed(0)} % de la película:
  deja fuera el material que no aporta.
- Orden cronológico estricto, sin solapes.
- Para cada episodio: inicio < cumbre < desenlace < fin, con al menos ${COLA_MINIMA} segundos
  entre \`desenlace\` y \`fin\` — ahí va el cierre en tensión.
- \`titulo\` sin numerar: el número de parte lo añade el sistema.
- \`cliffhanger\` del ÚLTIMO episodio: no dejes nada abierto, es el cierre de la historia.

Escribe titulo, razon, resumen, cliffhanger, tituloSerie y sinopsis en ${salida.nombre}.`;

  const respuesta = await pedirEstructurado(RespuestaSerieSchema, {
    sistema: SISTEMA_SERIE,
    prompt,
    etiqueta: "clips",
    maxTokens: 32000,
  });

  // Cortes visuales alrededor de cada frontera propuesta (no de toda la película).
  let cortes = new Map<number, number[]>();
  if (!sinEscenas) {
    const instantes = respuesta.episodios.flatMap((e) => [e.inicio, e.fin]);
    console.log(`· clips: buscando cambios de plano en ${instantes.length} fronteras…`);
    cortes = await detectarCortes(fuente.rutaOriginal, instantes);
  }

  const episodios: Episodio[] = respuesta.episodios.map((e) => {
    const ini = alinearCorte(e.inicio, "inicio", transcripcion, cortes.get(e.inicio) ?? [], fuente.fps);
    const fin = alinearCorte(e.fin, "fin", transcripcion, cortes.get(e.fin) ?? [], fuente.fps);
    return {
      ...e,
      inicio: Math.max(0, ini.tiempo),
      fin: Math.min(fuente.duracion, fin.tiempo),
      alineacion: { inicio: ini.modo, fin: fin.modo },
    };
  });

  const { clips, cobertura } = normalizarEpisodios(episodios, transcripcion, fuente.duracion);

  const resultado = await escribirJson(rutas.clips(videoId), ClipsSchema, {
    modelo: config.modeloLlm,
    formato: "serie",
    serie: {
      titulo: respuesta.tituloSerie,
      sinopsis: respuesta.sinopsis,
      totalPartes: clips.length,
      cobertura,
    },
    clips,
  });

  console.log(
    `· serie "${resultado.serie!.titulo}": ${clips.length} episodios, ` +
      `${(cobertura * 100).toFixed(0)} % de la película`,
  );
  for (const clip of resultado.clips) {
    const duracion = clip.fin - clip.inicio;
    const hueco = clip.huecoAnterior ? ` ·  salto ${clip.huecoAnterior.toFixed(0)}s` : "";
    console.log(
      `  Parte ${clip.parte}/${clip.totalPartes} ${clip.inicio.toFixed(1)}–${clip.fin.toFixed(1)}s ` +
        `(${duracion.toFixed(0)}s, cortes ${clip.alineacion!.inicio}/${clip.alineacion!.fin})${hueco} — ${clip.titulo}`,
    );
  }
  return resultado;
}

// ---------------------------------------------------------------------------

export interface OpcionesClips {
  /** Tope de piezas. En formato serie es "hasta N"; el material decide cuántas salen. */
  n?: number;
  force?: boolean;
  /** Idioma en que se escriben títulos, resúmenes y sinopsis; por defecto, el del audio. */
  idiomaSalida?: string;
  formato?: "serie" | "virales";
  sinEscenas?: boolean;
}

export async function seleccionarClips(
  videoId: string,
  opciones: OpcionesClips = {},
): Promise<Clips> {
  const fuente = await leerJson(rutas.fuente(videoId), FuenteSchema);
  const transcripcion = await leerJson(rutas.transcripcion(videoId), TranscripcionSchema);
  const formato = opciones.formato ?? "serie";

  // En serie el tope por defecto sale de la duración: pedir "5" en una película de 86 minutos
  // obligaría a saltarse casi toda la historia.
  const n =
    opciones.n ??
    (formato === "serie"
      ? Math.min(40, Math.max(2, Math.ceil(fuente.duracion / DURACION_OBJETIVO)))
      : 5);

  return pasoIdempotente({
    salida: rutas.clips(videoId),
    force: opciones.force ?? false,
    nombre: formato === "serie" ? "serie de episodios" : "selección de clips",
    leer: () => leerJson(rutas.clips(videoId), ClipsSchema),
    calcular: () =>
      formato === "serie"
        ? seleccionarSerie(
            videoId,
            fuente,
            transcripcion,
            n,
            opciones.idiomaSalida,
            opciones.sinEscenas ?? false,
          )
        : seleccionarVirales(videoId, fuente, transcripcion, n, opciones.idiomaSalida),
  });
}
