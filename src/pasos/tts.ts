/**
 * Paso 5 — Voz. Sintetiza con Edge-TTS el texto de cada tramo `narracion` del guion.
 *
 * Si el audio generado no cabe en su tramo se acelera con `atempo` (hasta 1.15×, más allá
 * suena a ardilla). Si aun así no cabe, se avisa: el montaje lo dejará sonar sobre el tramo
 * siguiente en vez de cortarlo a mitad de frase.
 */

import path from "node:path";
import { config } from "../config.js";
import { GuionSchema, NarracionSchema, type Narracion, type NarracionTramo } from "../tipos.js";
import { ClipsSchema } from "../tipos.js";
import { ejecutarJson } from "../lib/proceso.js";
import { duracionMedio } from "../lib/ffmpeg.js";
import { asegurarDir, escribirJson, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";
import { esIdiomaConocido, resolverIdioma } from "../lib/idiomas.js";
import type { Palabra } from "../tipos.js";

const TEMPO_MAX = 1.15;

interface SalidaTts {
  voz: string;
  archivo: string;
  palabras: Palabra[];
}

export interface OpcionesTts {
  force?: boolean;
  clip?: number;
}

/**
 * La voz sale del idioma del guion, no de la config: un mismo pipeline puede producir clips
 * en varios idiomas. `TTS_VOZ` sigue mandando si está definida, para forzar una voz concreta.
 */
function vozParaGuion(idiomaGuion: string): string {
  if (config.vozTts) return config.vozTts;
  if (!esIdiomaConocido(idiomaGuion)) {
    console.warn(
      `  · idioma "${idiomaGuion}" sin voz afinada: se usa la voz multilingüe. ` +
        `Fija TTS_VOZ si quieres otra.`,
    );
  }
  return resolverIdioma(idiomaGuion).voz;
}

async function sintetizarClip(videoId: string, indice: number, force: boolean): Promise<Narracion> {
  const guion = await leerJson(rutas.guion(videoId, indice), GuionSchema);
  const voz = vozParaGuion(guion.idioma);

  return pasoIdempotente({
    salida: rutas.narracion(videoId, indice),
    force,
    nombre: `tts clip #${indice}`,
    leer: () => leerJson(rutas.narracion(videoId, indice), NarracionSchema),
    calcular: async () => {
      const dirSalida = rutas.dirNarracion(videoId, indice);
      await asegurarDir(dirSalida);

      const tramos: NarracionTramo[] = [];
      for (const [posicion, tramo] of guion.tramos.entries()) {
        if (tramo.tipo !== "narracion" || !tramo.texto?.trim()) continue;

        const archivo = path.join(dirSalida, `${posicion}.mp3`);
        const salida = await ejecutarJson<SalidaTts>(
          config.python,
          [
            path.join(config.scriptsDir, "tts.py"),
            "--texto", tramo.texto,
            "--voz", voz,
            "--salida", archivo,
          ],
          { etiqueta: "edge-tts" },
        );

        const duracionAudio = await duracionMedio(archivo);
        const disponible = tramo.fin - tramo.inicio;

        let tempo = 1;
        if (duracionAudio > disponible) {
          tempo = Math.min(TEMPO_MAX, duracionAudio / disponible);
          const resultante = duracionAudio / tempo;
          if (resultante > disponible + 0.5) {
            console.warn(
              `  · clip #${indice} tramo ${posicion}: la narración dura ${resultante.toFixed(1)} s ` +
                `y el tramo ${disponible.toFixed(1)} s; invadirá el tramo siguiente.`,
            );
          }
        }

        tramos.push({
          tramo: posicion,
          archivo,
          desplazamiento: tramo.inicio,
          duracion: duracionAudio / tempo,
          tempo,
          // Los timings vienen relativos al mp3; con tempo != 1 se comprimen igual que el audio.
          palabras: salida.palabras.map((p) => ({
            texto: p.texto,
            inicio: p.inicio / tempo,
            fin: p.fin / tempo,
          })),
        });
      }

      const narracion = await escribirJson(rutas.narracion(videoId, indice), NarracionSchema, {
        voz,
        tramos,
      });
      console.log(
        `· tts #${indice}: ${tramos.length} tramos narrados (${voz}, ${guion.idioma})`,
      );
      return narracion;
    },
  });
}

export async function sintetizarNarraciones(
  videoId: string,
  opciones: OpcionesTts = {},
): Promise<Narracion[]> {
  const { clips } = await leerJson(rutas.clips(videoId), ClipsSchema);
  const indices =
    opciones.clip === undefined ? clips.map((c) => c.indice) : [opciones.clip];

  const narraciones: Narracion[] = [];
  for (const indice of indices) {
    narraciones.push(await sintetizarClip(videoId, indice, opciones.force ?? false));
  }
  return narraciones;
}
