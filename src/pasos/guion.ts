/**
 * Paso 4 — Guion por clip: hook, reparto del clip en tramos de narración y audio original,
 * caption y hashtags (Módulo 03 de la propuesta técnica).
 *
 * La decisión de diseño clave: el clip conserva su duración y el LLM decide **dónde** entra
 * la voz. En los tramos `narracion` el audio ambiental se atenúa (ducking) y encima suena la
 * voz; en los `original` suena el clip tal cual. Los tramos cubren el clip entero, en orden y
 * sin huecos — el montaje depende de esa invariante.
 */

import { z } from "zod";
import {
  ClipsSchema,
  GuionSchema,
  TranscripcionSchema,
  type Clip,
  type Guion,
  type Tramo,
  type Transcripcion,
} from "../tipos.js";
import { pedirEstructurado } from "../lib/llm.js";
import { escribirJson, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";

/** Ritmo aproximado de Edge-TTS en español, en palabras por segundo. */
const PALABRAS_POR_SEGUNDO = 2.6;
/** Margen que se deja libre al final de un tramo narrado para que la voz no pise el siguiente. */
const MARGEN = 0.3;

const RespuestaSchema = z.object({
  hook: z.string().describe("Frase de gancho que se superpone en los primeros 1.5 s del clip"),
  tramos: z
    .array(
      z.object({
        tipo: z.enum(["original", "narracion"]),
        inicio: z.number().describe("Segundo de inicio dentro del clip (0 = principio del clip)"),
        fin: z.number().describe("Segundo de fin dentro del clip"),
        texto: z
          .string()
          .describe("Texto a narrar. Cadena vacía en los tramos de tipo 'original'."),
      }),
    )
    .describe("Tramos consecutivos que cubren el clip completo, sin huecos ni solapes"),
  caption: z.string().describe("Texto de publicación, sin hashtags"),
  hashtags: z.array(z.string()).describe("Hashtags sin el símbolo #"),
});

const SISTEMA = `Eres guionista de contenido vertical viral (TikTok, Reels, Shorts) en español.

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

Reglas de los tramos:
- Cubren el clip completo, empiezan en 0 y terminan en la duración exacta del clip.
- Van en orden, sin huecos ni solapes: el fin de uno es el inicio del siguiente.
- Un tramo narrado dura al menos 3 segundos.
- El texto narrado debe caber en su tramo hablando a ritmo natural (unas 2.6 palabras por
  segundo). Si no cabe, acórtalo: es mejor una frase corta y clara que una atropellada.
- Los tramos "original" llevan texto vacío.`;

function contarPalabras(texto: string): number {
  return texto.trim().split(/\s+/).filter(Boolean).length;
}

/**
 * Fuerza la invariante que necesita el montaje: tramos ordenados, encadenados y cubriendo
 * exactamente [0, duracion]. Recorta el texto narrado que no quepa en su tramo.
 */
function normalizarTramos(
  propuestos: z.infer<typeof RespuestaSchema>["tramos"],
  duracion: number,
): Tramo[] {
  const ordenados = [...propuestos]
    .filter((t) => t.fin > t.inicio)
    .sort((a, b) => a.inicio - b.inicio);

  if (ordenados.length === 0) {
    return [{ tipo: "original", inicio: 0, fin: duracion }];
  }

  const tramos: Tramo[] = [];
  let cursor = 0;
  for (const [i, propuesto] of ordenados.entries()) {
    const esUltimo = i === ordenados.length - 1;
    const fin = esUltimo ? duracion : Math.min(propuesto.fin, duracion);
    if (fin - cursor < 0.5) continue; // tramo residual: se absorbe en el anterior

    const tramo: Tramo = { tipo: propuesto.tipo, inicio: cursor, fin };
    if (propuesto.tipo === "narracion") {
      const disponible = fin - cursor - MARGEN;
      const maxPalabras = Math.max(1, Math.floor(disponible * PALABRAS_POR_SEGUNDO));
      const palabras = propuesto.texto.trim().split(/\s+/).filter(Boolean);
      if (palabras.length === 0) {
        tramo.tipo = "original";
      } else if (palabras.length > maxPalabras) {
        tramo.texto = palabras.slice(0, maxPalabras).join(" ");
        console.warn(
          `  · tramo ${cursor.toFixed(1)}–${fin.toFixed(1)}s: narración recortada de ` +
            `${palabras.length} a ${maxPalabras} palabras para que quepa.`,
        );
      } else {
        tramo.texto = propuesto.texto.trim();
      }
    }
    tramos.push(tramo);
    cursor = fin;
  }

  if (tramos.length === 0) return [{ tipo: "original", inicio: 0, fin: duracion }];
  const ultimo = tramos[tramos.length - 1]!;
  ultimo.fin = duracion;
  return tramos;
}

/** Porción de la transcripción que cae dentro del clip, con tiempos relativos al clip. */
function transcripcionDelClip(transcripcion: Transcripcion, clip: Clip): string {
  return transcripcion.segmentos
    .filter((s) => s.fin > clip.inicio && s.inicio < clip.fin)
    .map((s) => `[${(s.inicio - clip.inicio).toFixed(1)}] ${s.texto}`)
    .join("\n");
}

export interface OpcionesGuion {
  force?: boolean;
  clip?: number;
  /** Sin TTS el clip conserva su audio original completo: un único tramo. */
  sinTts?: boolean;
}

export async function generarGuiones(
  videoId: string,
  opciones: OpcionesGuion = {},
): Promise<Guion[]> {
  const { clips } = await leerJson(rutas.clips(videoId), ClipsSchema);
  const transcripcion = await leerJson(rutas.transcripcion(videoId), TranscripcionSchema);

  const seleccionados =
    opciones.clip === undefined ? clips : clips.filter((c) => c.indice === opciones.clip);
  if (seleccionados.length === 0) {
    throw new Error(`No existe el clip ${opciones.clip} en ${rutas.clips(videoId)}`);
  }

  const guiones: Guion[] = [];
  for (const clip of seleccionados) {
    const guion = await pasoIdempotente({
      salida: rutas.guion(videoId, clip.indice),
      force: opciones.force ?? false,
      nombre: `guion clip #${clip.indice}`,
      leer: () => leerJson(rutas.guion(videoId, clip.indice), GuionSchema),
      calcular: async () => {
        const duracion = clip.fin - clip.inicio;
        const prompt = `Clip #${clip.indice} — "${clip.titulo}" (${duracion.toFixed(1)} segundos).
Por qué se eligió: ${clip.razon}

Transcripción del clip (tiempos relativos a su inicio):
${transcripcionDelClip(transcripcion, clip) || "(sin habla)"}

Escribe el guion. Los tramos deben cubrir de 0 a ${duracion.toFixed(1)} segundos.`;

        const respuesta = await pedirEstructurado(RespuestaSchema, {
          sistema: SISTEMA,
          prompt,
          etiqueta: `guion #${clip.indice}`,
        });

        const tramos = opciones.sinTts
          ? ([{ tipo: "original", inicio: 0, fin: duracion }] as Tramo[])
          : normalizarTramos(respuesta.tramos, duracion);

        const resultado = await escribirJson(rutas.guion(videoId, clip.indice), GuionSchema, {
          indice: clip.indice,
          hook: respuesta.hook,
          tramos,
          caption: respuesta.caption,
          hashtags: respuesta.hashtags.map((h) => h.replace(/^#/, "")),
        });

        const narrados = tramos.filter((t) => t.tipo === "narracion");
        const palabras = narrados.reduce((n, t) => n + contarPalabras(t.texto ?? ""), 0);
        console.log(
          `· guion #${clip.indice}: "${resultado.hook}" — ${tramos.length} tramos ` +
            `(${narrados.length} narrados, ${palabras} palabras)`,
        );
        return resultado;
      },
    });
    guiones.push(guion);
  }
  return guiones;
}
