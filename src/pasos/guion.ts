/**
 * Paso 4 — Guion por pieza: hook, reparto en tramos de narración y audio original, caption y
 * hashtags (Módulo 03 de la propuesta técnica).
 *
 * La decisión de diseño clave: la pieza conserva su duración y el LLM decide **dónde** entra
 * la voz. En los tramos `narracion` el audio ambiental se atenúa (ducking) y encima suena la
 * voz; en los `original` suena el clip tal cual. Los tramos cubren la pieza entera, en orden y
 * sin huecos — el montaje depende de esa invariante.
 *
 * En formato serie hay además continuidad: cada episodio abre con un recap narrado de la
 * entrega anterior y cierra verbalizando la tensión que queda abierta. Ese recap NO se deja a
 * criterio del modelo: el sistema lo inserta como primer tramo, para que la invariante se
 * cumpla incluso si el LLM lo ignora.
 */

import { z } from "zod";
import {
  ClipsSchema,
  GuionSchema,
  TranscripcionSchema,
  type Clip,
  type Guion,
  type Serie,
  type Tramo,
  type Transcripcion,
} from "../tipos.js";
import { config } from "../config.js";
import { pedirEstructurado } from "../lib/llm.js";
import { escribirJson, existe, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";
import { resolverIdioma, type Idioma } from "../lib/idiomas.js";

/** Margen que se deja libre al final de un tramo narrado para que la voz no pise el siguiente. */
const MARGEN = 0.3;
/** Duración del recap que abre cada episodio a partir del segundo. */
const RECAP_SEG = 8;
/** Más de esto de voz en off seguida tapa la película; el tramo se parte. */
const TRAMO_NARRACION_MAX = 20;
/** Densidad de narración admisible: el suelo es transformatividad, el techo dejar respirar. */
const NARRACION_MIN = 0.4;
const NARRACION_MAX = 0.65;

const RespuestaSchema = z.object({
  hook: z.string().describe("Frase de gancho que se superpone al principio de la pieza"),
  recap: z
    .string()
    .describe(
      "Solo en serie y a partir de la parte 2: voz en off que sitúa a quien no vio la entrega " +
        "anterior. Cadena vacía en la parte 1 y en formato virales.",
    ),
  tramos: z
    .array(
      z.object({
        tipo: z.enum(["original", "narracion"]),
        inicio: z.number().describe("Segundo de inicio dentro de la pieza"),
        fin: z.number().describe("Segundo de fin dentro de la pieza"),
        texto: z
          .string()
          .describe("Texto a narrar. Cadena vacía en los tramos de tipo 'original'."),
      }),
    )
    .describe("Tramos consecutivos que cubren la pieza completa, sin huecos ni solapes"),
  resumen: z
    .string()
    .describe("2-3 frases de lo que se cuenta en esta pieza; alimenta el recap de la siguiente"),
  cliffhanger: z.string().describe("Tensión que queda abierta al final, en una frase"),
  caption: z.string().describe("Texto de publicación, sin hashtags ni número de parte"),
  hashtags: z.array(z.string()).describe("Hashtags sin el símbolo #"),
});

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

function sistemaVirales(idiomaSalida: string, palabrasPorSegundo: number): string {
  return `Eres guionista de contenido vertical viral (TikTok, Reels, Shorts).

Escribes TODO el texto de salida —hook, narración, caption y hashtags— en ${idiomaSalida},
aunque el video esté hablado en otro idioma. En ese caso no traduces literalmente: cuentas lo
que pasa a quien no entiende el idioma original.

Para cada clip escribes:
1. Un HOOK: una frase de menos de 8 palabras que aparece en pantalla en el primer segundo y
   obliga a seguir viendo. Nunca es un resumen; es una pregunta, una tensión o una promesa.
2. Un reparto del clip en TRAMOS consecutivos:
   - "original": suena el audio del clip tal cual. Úsalo cuando lo que ocurre se explica solo
     o cuando el audio ambiental es la parte potente (una frase fuerte, una reacción, música).
   - "narracion": entra una voz en off que aporta contexto, tensión o remate. El audio
     ambiental sigue oyéndose de fondo, atenuado.
   Alternas ambos: la narración continua aburre y tapa el material; el audio original sin
   contexto pierde a quien no vio el resto del video.
3. Un caption y hashtags optimizados para descubrimiento.

Deja \`recap\` y \`cliffhanger\` como cadena vacía: no aplican fuera del formato serie.

Reglas de los tramos:
- Cubren el clip completo, empiezan en 0 y terminan en la duración exacta del clip.
- Van en orden, sin huecos ni solapes: el fin de uno es el inicio del siguiente.
- Un tramo narrado dura al menos 3 segundos.
- El texto narrado debe caber en su tramo hablando a ritmo natural (unas ${palabrasPorSegundo}
  palabras por segundo en ${idiomaSalida}). Si no cabe, acórtalo: es mejor una frase corta y
  clara que una atropellada.
- Los tramos "original" llevan texto vacío.`;
}

interface DatosSistemaSerie {
  idiomaSalida: string;
  palabrasPorSegundo: number;
  parte: number;
  totalPartes: number;
  tituloSerie: string;
  duracion: number;
  /** Desde dónde empiezan los tramos del LLM: 0 en la parte 1, RECAP_SEG en el resto. */
  desde: number;
  maxOriginal: number;
  maxPalabrasRecap: number;
  arco?: { cumbre: number; desenlace: number };
}

function sistemaSerie(d: DatosSistemaSerie): string {
  const esPrimero = d.parte === 1;
  const esUltimo = d.parte === d.totalPartes;

  return `Eres guionista de una SERIE vertical. Este es el EPISODIO ${d.parte} de ${d.totalPartes} de
"${d.tituloSerie}". El espectador puede llegar sin haber visto los anteriores, y tiene que
terminar queriendo el siguiente.

Escribes TODO el texto de salida en ${d.idiomaSalida}, aunque el material esté hablado en otro
idioma. En ese caso no traduces literalmente: cuentas lo que pasa a quien no lo entiende.

Escribes para este episodio:
${
  esPrimero
    ? `1. RECAP: cadena vacía. Este es el primer episodio, no hay nada que recapitular.`
    : `1. RECAP: ${RECAP_SEG} segundos de voz en off que sitúan a quien llega nuevo y retoman la
   tensión con la que cerró la entrega anterior. Empieza POR la tensión, no por el resumen.
   Máximo ${d.maxPalabrasRecap} palabras. NO forma parte de tus \`tramos\`: el sistema lo coloca
   en los primeros ${RECAP_SEG} segundos.`
}
2. HOOK: menos de 8 palabras en pantalla. No es un resumen; es la promesa de este episodio.
   No escribas el número de parte: lo añade el sistema.
3. TRAMOS que cubren de ${d.desde} a ${d.duracion.toFixed(1)} segundos.
4. RESUMEN: 2-3 frases con lo que ocurre en ESTE episodio. Lo usará el recap del siguiente.
5. CLIFFHANGER: ${
    esUltimo
      ? "es el último episodio, así que aquí cierras la historia en vez de abrir nada."
      : "la tensión que queda abierta al final, en una frase."
  }
6. CAPTION y HASHTAGS. El caption no lleva el número de parte ni la llamada a seguir la cuenta:
   los añade el sistema.

Reglas de los tramos (episodio de ${d.duracion.toFixed(0)} segundos):
- Cubren de ${d.desde} a ${d.duracion.toFixed(1)}, en orden, sin huecos ni solapes.
- Entre 10 y 20 tramos. Un episodio de varios minutos con 3 tramos es un muro: alterna.
- Un tramo "narracion" dura entre 4 y ${TRAMO_NARRACION_MAX} segundos. Más voz en off seguida
  tapa la película y el espectador se va.
- Un tramo "original" dura como mucho ${d.maxOriginal} segundos.
- La narración total ocupa entre el ${Math.round(NARRACION_MIN * 100)} % y el ${Math.round(
    NARRACION_MAX * 100,
  )} % del episodio: aportas contexto, pero la película tiene que respirar.
- El texto narrado cabe en su tramo a ritmo natural (~${d.palabrasPorSegundo} palabras/segundo).
- Los tramos "original" llevan texto vacío.
- El ÚLTIMO tramo es "narracion" de 4 a 8 segundos: ${
    esUltimo
      ? "cierra la historia y remite al perfil para ver la serie completa."
      : "verbaliza la tensión que queda abierta y remite a la entrega siguiente. Nunca la resuelvas."
  }${
    d.arco
      ? `
- Alrededor del segundo ${d.arco.cumbre.toFixed(0)} está el pico de tensión: deja sonar el
  material original ahí, no narres encima. Alrededor del ${d.arco.desenlace.toFixed(
    0,
  )} se cierra el arco.`
      : ""
  }`;
}

// ---------------------------------------------------------------------------
// Normalización de tramos
// ---------------------------------------------------------------------------

function contarPalabras(texto: string): number {
  return texto.trim().split(/\s+/).filter(Boolean).length;
}

function recortarAPalabras(texto: string, segundos: number, palabrasPorSegundo: number): string {
  const maximo = Math.max(1, Math.floor((segundos - MARGEN) * palabrasPorSegundo));
  const palabras = texto.trim().split(/\s+/).filter(Boolean);
  return palabras.length <= maximo ? palabras.join(" ") : palabras.slice(0, maximo).join(" ");
}

/**
 * Fuerza la invariante que necesita el montaje: tramos ordenados, encadenados y cubriendo
 * exactamente [desde, hasta]. Recorta el texto narrado que no quepa y parte los tramos de voz
 * demasiado largos.
 */
function normalizarTramos(
  propuestos: z.infer<typeof RespuestaSchema>["tramos"],
  desde: number,
  hasta: number,
  palabrasPorSegundo: number,
): Tramo[] {
  const ordenados = [...propuestos]
    .filter((t) => t.fin > t.inicio)
    .sort((a, b) => a.inicio - b.inicio);

  if (ordenados.length === 0) {
    return [{ tipo: "original", inicio: desde, fin: hasta }];
  }

  const tramos: Tramo[] = [];
  let cursor = desde;
  for (const [i, propuesto] of ordenados.entries()) {
    const esUltimo = i === ordenados.length - 1;
    const fin = esUltimo ? hasta : Math.min(Math.max(propuesto.fin, cursor), hasta);
    if (fin - cursor < 0.5) continue; // tramo residual: se absorbe en el anterior

    if (propuesto.tipo === "original") {
      tramos.push({ tipo: "original", inicio: cursor, fin });
      cursor = fin;
      continue;
    }

    const palabras = propuesto.texto.trim().split(/\s+/).filter(Boolean);
    if (palabras.length === 0) {
      tramos.push({ tipo: "original", inicio: cursor, fin });
      cursor = fin;
      continue;
    }

    // Voz en off demasiado larga: se narra el principio y el resto queda en audio original.
    const finVoz = Math.min(fin, cursor + TRAMO_NARRACION_MAX);
    const disponible = finVoz - cursor - MARGEN;
    const maxPalabras = Math.max(1, Math.floor(disponible * palabrasPorSegundo));
    const texto =
      palabras.length > maxPalabras ? palabras.slice(0, maxPalabras).join(" ") : palabras.join(" ");
    if (palabras.length > maxPalabras) {
      console.warn(
        `  · tramo ${cursor.toFixed(1)}–${finVoz.toFixed(1)}s: narración recortada de ` +
          `${palabras.length} a ${maxPalabras} palabras para que quepa.`,
      );
    }
    tramos.push({ tipo: "narracion", inicio: cursor, fin: finVoz, texto });
    if (fin - finVoz >= 0.5) tramos.push({ tipo: "original", inicio: finVoz, fin });
    cursor = fin;
  }

  if (tramos.length === 0) return [{ tipo: "original", inicio: desde, fin: hasta }];
  tramos[tramos.length - 1]!.fin = hasta;
  return tramos;
}

/** Porción de la transcripción que cae dentro de la pieza, con tiempos relativos a ella. */
function transcripcionDelClip(transcripcion: Transcripcion, clip: Clip): string {
  return transcripcion.segmentos
    .filter((s) => s.fin > clip.inicio && s.inicio < clip.fin)
    .map((s) => `[${(s.inicio - clip.inicio).toFixed(1)}] ${s.texto}`)
    .join("\n");
}

// ---------------------------------------------------------------------------
// Continuidad entre episodios
// ---------------------------------------------------------------------------

interface ContextoPrevio {
  parte: number;
  titulo: string;
  resumen: string;
  cliffhanger: string;
  /** Segundos del fuente saltados entre el episodio anterior y este. */
  hueco: number;
}

/**
 * Contexto del episodio anterior, en cascada de tres fuentes: lo generado en esta ejecución,
 * el guion ya escrito en disco, y por último el plan de clips.json.
 *
 * La cascada es lo que hace que la continuidad no dependa de si el guion anterior se calculó
 * ahora o se leyó de disco (`pasoIdempotente` devuelve ambos por el mismo camino), ni de si se
 * está regenerando un episodio suelto con `--clip N`.
 */
async function contextoPrevio(
  videoId: string,
  clips: Clip[],
  actual: Clip,
  enMemoria: Map<number, Guion>,
): Promise<ContextoPrevio | undefined> {
  if (!actual.parte || actual.parte === 1) return undefined;
  const anterior = clips.find((c) => c.indice === actual.indice - 1);
  if (!anterior) return undefined;

  const base = {
    parte: anterior.parte ?? actual.parte - 1,
    titulo: anterior.titulo,
    hueco: Math.max(0, actual.inicio - anterior.fin),
  };

  const enMem = enMemoria.get(anterior.indice);
  if (enMem?.resumen) {
    return { ...base, resumen: enMem.resumen, cliffhanger: enMem.cliffhanger ?? "" };
  }

  const ruta = rutas.guion(videoId, anterior.indice);
  if (await existe(ruta)) {
    const guion = await leerJson(ruta, GuionSchema);
    if (guion.resumen) {
      return { ...base, resumen: guion.resumen, cliffhanger: guion.cliffhanger ?? "" };
    }
  }

  return {
    ...base,
    resumen: anterior.resumen ?? anterior.razon,
    cliffhanger: anterior.cliffhanger ?? "",
  };
}

/** Recap de emergencia cuando el LLM no devolvió uno: nunca se deja el tramo vacío. */
function recapDeRespaldo(previo: ContextoPrevio): string {
  const cierre = previo.cliffhanger?.trim();
  return cierre ? `${previo.resumen} ${cierre}`.trim() : previo.resumen;
}

// ---------------------------------------------------------------------------

export interface OpcionesGuion {
  force?: boolean;
  clip?: number;
  /** Sin TTS la pieza conserva su audio original completo: un único tramo. */
  sinTts?: boolean;
  /** Idioma de hook, narración y caption; por defecto, el del audio. */
  idiomaSalida?: string;
}

export async function generarGuiones(
  videoId: string,
  opciones: OpcionesGuion = {},
): Promise<Guion[]> {
  const { clips, formato, serie } = await leerJson(rutas.clips(videoId), ClipsSchema);
  const transcripcion = await leerJson(rutas.transcripcion(videoId), TranscripcionSchema);

  const origen = resolverIdioma(transcripcion.idioma);
  const salida = resolverIdioma(opciones.idiomaSalida?.trim() || transcripcion.idioma);
  const traduce = salida.codigo !== origen.codigo;
  if (traduce) {
    console.log(`· guion: audio en ${origen.nombre} → contenido en ${salida.nombre}`);
  }

  // El orden importa: el contexto de un episodio sale del anterior.
  const seleccionados = (
    opciones.clip === undefined ? [...clips] : clips.filter((c) => c.indice === opciones.clip)
  ).sort((a, b) => a.indice - b.indice);
  if (seleccionados.length === 0) {
    throw new Error(`No existe el clip ${opciones.clip} en ${rutas.clips(videoId)}`);
  }

  const enMemoria = new Map<number, Guion>();
  const guiones: Guion[] = [];

  for (const clip of seleccionados) {
    const guion = await pasoIdempotente({
      salida: rutas.guion(videoId, clip.indice),
      force: opciones.force ?? false,
      nombre: formato === "serie" ? `guion parte ${clip.parte}` : `guion clip #${clip.indice}`,
      leer: () => leerJson(rutas.guion(videoId, clip.indice), GuionSchema),
      calcular: () =>
        generarGuion({
          videoId,
          clip,
          clips,
          formato,
          serie,
          transcripcion,
          origen,
          salida,
          traduce,
          sinTts: opciones.sinTts ?? false,
          enMemoria,
        }),
    });
    enMemoria.set(clip.indice, guion);
    guiones.push(guion);
  }
  return guiones;
}

interface DatosGuion {
  videoId: string;
  clip: Clip;
  clips: Clip[];
  formato: "serie" | "virales";
  serie?: Serie;
  transcripcion: Transcripcion;
  origen: ReturnType<typeof resolverIdioma>;
  salida: ReturnType<typeof resolverIdioma>;
  traduce: boolean;
  sinTts: boolean;
  enMemoria: Map<number, Guion>;
}

async function generarGuion(d: DatosGuion): Promise<Guion> {
  const { clip, salida, origen } = d;
  const duracion = clip.fin - clip.inicio;
  const esSerie = d.formato === "serie" && clip.parte !== undefined;
  const parte = clip.parte ?? clip.indice + 1;
  const totalPartes = clip.totalPartes ?? d.clips.length;

  const previo = esSerie
    ? await contextoPrevio(d.videoId, d.clips, clip, d.enMemoria)
    : undefined;
  const desde = previo ? RECAP_SEG : 0;
  const maxPalabrasRecap = Math.floor((RECAP_SEG - MARGEN) * salida.palabrasPorSegundo);

  const sistema = esSerie
    ? sistemaSerie({
        idiomaSalida: salida.nombre,
        palabrasPorSegundo: salida.palabrasPorSegundo,
        parte,
        totalPartes,
        tituloSerie: d.serie?.titulo ?? "",
        duracion,
        desde,
        maxOriginal: d.traduce ? 25 : 35,
        maxPalabrasRecap,
        arco: clip.arco,
      })
    : sistemaVirales(salida.nombre, salida.palabrasPorSegundo);

  const cabecera = esSerie
    ? `Episodio ${parte} de ${totalPartes} — "${clip.titulo}" (${duracion.toFixed(1)} segundos).`
    : `Clip #${clip.indice} — "${clip.titulo}" (${duracion.toFixed(1)} segundos).`;

  const contexto = previo
    ? `\nDe qué venimos (parte ${previo.parte}, "${previo.titulo}"):
${previo.resumen}${previo.cliffhanger ? `\nQuedó abierto: ${previo.cliffhanger}` : ""}${
        previo.hueco > 5
          ? `\nEntre aquel episodio y este se saltan ${previo.hueco.toFixed(
              0,
            )} segundos de película: el recap tiene que cubrir ese salto.`
          : ""
      }\n`
    : "";

  const prompt = `${cabecera}
Por qué se eligió: ${clip.razon}
${contexto}
Transcripción de la pieza en ${origen.nombre} (tiempos relativos a su inicio):
${transcripcionDelClip(d.transcripcion, clip) || "(sin habla)"}

${
  d.traduce
    ? `El audio original está en ${origen.nombre} y el público no lo entiende: apóyate más en
tramos narrados y deja tramos "original" solo donde la imagen, la música o la emoción se
expliquen sin palabras.\n\n`
    : ""
}Escribe el guion en ${salida.nombre}. Los tramos deben cubrir de ${desde} a ${duracion.toFixed(
    1,
  )} segundos.`;

  const respuesta = await pedirEstructurado(RespuestaSchema, {
    sistema,
    prompt,
    etiqueta: esSerie ? `guion parte ${parte}` : `guion #${clip.indice}`,
  });

  let tramos: Tramo[];
  if (d.sinTts) {
    tramos = [{ tipo: "original", inicio: 0, fin: duracion }];
  } else {
    tramos = normalizarTramos(respuesta.tramos, desde, duracion, salida.palabrasPorSegundo);
    if (previo) {
      // El recap lo inserta el sistema: así la parte 2 en adelante SIEMPRE abre situando al
      // espectador, aunque el modelo lo haya omitido.
      const texto = recortarAPalabras(
        respuesta.recap?.trim() || recapDeRespaldo(previo),
        RECAP_SEG,
        salida.palabrasPorSegundo,
      );
      tramos.unshift({ tipo: "narracion", inicio: 0, fin: RECAP_SEG, texto });
    }
  }

  const caption = esSerie
    ? componerCaption(respuesta.caption, parte, totalPartes, salida)
    : respuesta.caption;

  const resultado = await escribirJson(rutas.guion(d.videoId, clip.indice), GuionSchema, {
    indice: clip.indice,
    idioma: salida.codigo,
    hook: respuesta.hook,
    tramos,
    caption,
    hashtags: respuesta.hashtags.map((h) => h.replace(/^#/, "")),
    ...(esSerie
      ? {
          parte,
          totalPartes,
          recap: previo ? (tramos[0]?.texto ?? "") : "",
          resumen: respuesta.resumen,
          cliffhanger: respuesta.cliffhanger,
        }
      : {}),
  });

  const narrados = tramos.filter((t) => t.tipo === "narracion");
  const segundosNarrados = narrados.reduce((s, t) => s + (t.fin - t.inicio), 0);
  const densidad = segundosNarrados / duracion;
  const palabras = narrados.reduce((n, t) => n + contarPalabras(t.texto ?? ""), 0);

  if (esSerie && !d.sinTts) {
    if (densidad < NARRACION_MIN) {
      console.warn(
        `  · parte ${parte}: solo ${(densidad * 100).toFixed(0)} % narrado (mínimo ` +
          `${Math.round(NARRACION_MIN * 100)} %): poco aporte propio, ver docs/riesgos.md.`,
      );
    } else if (densidad > NARRACION_MAX) {
      console.warn(
        `  · parte ${parte}: ${(densidad * 100).toFixed(0)} % narrado (máximo ` +
          `${Math.round(NARRACION_MAX * 100)} %): la voz en off tapa la película.`,
      );
    }
    if (tramos[tramos.length - 1]?.tipo !== "narracion") {
      console.warn(`  · parte ${parte}: el episodio no cierra con voz en off; pierde el gancho.`);
    }
  }

  console.log(
    `· ${esSerie ? `guion parte ${parte}/${totalPartes}` : `guion #${clip.indice}`}: ` +
      `"${resultado.hook}" — ${tramos.length} tramos (${narrados.length} narrados, ` +
      `${palabras} palabras, ${(densidad * 100).toFixed(0)} % narrado)`,
  );
  return resultado;
}

/**
 * Numeración y llamada a la acción: las garantiza el código, no el modelo. Van en el idioma de
 * salida, salvo que `SERIE_CTA` las fije a mano.
 */
function componerCaption(
  texto: string,
  parte: number,
  totalPartes: number,
  idioma: Idioma,
): string {
  // El modelo a veces numera por su cuenta pese a pedirle que no: se quita y se rehace.
  const limpio = texto
    .trim()
    .replace(/^(parte|part|partie|teil)\s*\d+\s*(?:\/\s*\d+)?\s*[—\-:·]?\s*/i, "");
  const cta =
    parte < totalPartes
      ? config.serieCta || idioma.serie.cta
      : config.serieCtaFinal || idioma.serie.ctaFinal;
  return `${idioma.serie.parte(parte, totalPartes)} — ${limpio}\n\n${cta}`;
}
