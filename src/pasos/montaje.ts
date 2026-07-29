/**
 * Paso 6 — Montaje. Recorta el fragmento del video fuente, lo lleva a vertical 1080×1920 y
 * mezcla el audio ambiental con la narración aplicando ducking (Módulo 04 de la propuesta).
 *
 * Produce `base.mp4`: un clip que ya se ve y se oye como el resultado final, sin subtítulos
 * ni plantilla. Es el checkpoint donde se valida lo más frágil del pipeline — la mezcla —
 * sin esperar a un render de Remotion.
 */

import { existe, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";
import { construirBase, type NarracionEnMezcla, type Reencuadre } from "../lib/ffmpeg.js";
import {
  ClipsSchema,
  FuenteSchema,
  GuionSchema,
  NarracionSchema,
  type Clip,
  type Fuente,
} from "../tipos.js";

export interface OpcionesMontaje {
  force?: boolean;
  clip?: number;
  reencuadre?: Reencuadre;
  sinTts?: boolean;
}

async function montarClip(
  fuente: Fuente,
  clip: Clip,
  opciones: Required<Pick<OpcionesMontaje, "force" | "reencuadre" | "sinTts">>,
): Promise<string> {
  const videoId = fuente.videoId;
  const salida = rutas.base(videoId, clip.indice);

  return pasoIdempotente({
    salida,
    force: opciones.force,
    nombre: `montaje clip #${clip.indice}`,
    leer: async () => salida,
    calcular: async () => {
      const guion = await leerJson(rutas.guion(videoId, clip.indice), GuionSchema);
      const duracion = clip.fin - clip.inicio;

      let narraciones: NarracionEnMezcla[] = [];
      let tramosNarrados: { inicio: number; fin: number }[] = [];

      if (!opciones.sinTts && (await existe(rutas.narracion(videoId, clip.indice)))) {
        const narracion = await leerJson(rutas.narracion(videoId, clip.indice), NarracionSchema);
        narraciones = narracion.tramos.map((t) => ({
          archivo: t.archivo,
          desplazamiento: t.desplazamiento,
          tempo: t.tempo,
        }));
        // El ducking cubre lo que dura la voz de verdad, no el tramo completo del guion:
        // así el audio ambiental vuelve a volumen pleno en cuanto la narración termina.
        tramosNarrados = narracion.tramos.map((t) => ({
          inicio: t.desplazamiento,
          fin: Math.min(duracion, t.desplazamiento + t.duracion),
        }));
      } else if (!opciones.sinTts) {
        console.warn(
          `· montaje #${clip.indice}: no hay narración sintetizada; se monta con audio original.`,
        );
      }

      console.log(
        `· montaje #${clip.indice}: ${duracion.toFixed(1)} s, reencuadre ${opciones.reencuadre}, ` +
          `${narraciones.length} pistas de narración…`,
      );

      await construirBase({
        fuente: fuente.rutaOriginal,
        inicio: clip.inicio,
        duracion,
        reencuadre: opciones.reencuadre,
        tramosNarrados,
        narraciones,
        salida,
        onProgreso: (linea) => {
          const progreso = linea.match(/time=(\d+:\d+:\d+\.\d+)/);
          if (progreso) process.stdout.write(`\r  ${progreso[1]} / ${duracion.toFixed(1)}s`);
        },
      });
      process.stdout.write("\r");
      console.log(`  → ${salida} (hook: "${guion.hook}")`);
      return salida;
    },
  });
}

export async function montarClips(videoId: string, opciones: OpcionesMontaje = {}): Promise<string[]> {
  const fuente = await leerJson(rutas.fuente(videoId), FuenteSchema);
  const { clips } = await leerJson(rutas.clips(videoId), ClipsSchema);

  const seleccionados =
    opciones.clip === undefined ? clips : clips.filter((c) => c.indice === opciones.clip);
  if (seleccionados.length === 0) {
    throw new Error(`No existe el clip ${opciones.clip} en ${rutas.clips(videoId)}`);
  }

  const salidas: string[] = [];
  for (const clip of seleccionados) {
    salidas.push(
      await montarClip(fuente, clip, {
        force: opciones.force ?? false,
        reencuadre: opciones.reencuadre ?? "center",
        sinTts: opciones.sinTts ?? false,
      }),
    );
  }
  return salidas;
}
