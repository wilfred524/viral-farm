/**
 * Paso 7 — Render. Monta sobre `base.mp4` los subtítulos karaoke y la plantilla de marca con
 * Remotion, y genera además un preview recomprimido para la aprobación por Telegram (Fase 2).
 *
 * Se usa la API programática (`bundle` + `renderMedia`) en vez de la CLI de Remotion para que
 * el paso sea invocable igual desde la CLI de hoy y desde el worker de la Fase 2.
 */

import path from "node:path";
import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import { config } from "../config.js";
import {
  ClipsSchema,
  FuenteSchema,
  GuionSchema,
  NarracionSchema,
  TranscripcionSchema,
  type Clip,
  type PropsClip,
  type Subtitulo,
  type Transcripcion,
} from "../tipos.js";
import { existe, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";
import { comprimirPreview } from "../lib/ffmpeg.js";
import { verificarEspacio, verificarEspacioParaSerie } from "../lib/disco.js";

export interface OpcionesRender {
  force?: boolean;
  clip?: number;
}

/** Cachea el bundle: compilarlo una vez por ejecución en vez de una por clip. */
let bundlePromesa: Promise<string> | undefined;

function obtenerBundle(): Promise<string> {
  bundlePromesa ??= bundle({
    entryPoint: path.join(config.remotionDir, "index.ts"),
    publicDir: config.mediaDir,
    // Sin symlink, Remotion copiaría todo MEDIA_DIR dentro del bundle en cada render.
    symlinkPublicDir: true,
    onProgress: (porcentaje) => {
      if (porcentaje % 25 === 0) console.log(`· bundle Remotion: ${porcentaje}%`);
    },
  });
  return bundlePromesa;
}

/**
 * Construye la pista de subtítulos del clip: las palabras del audio original en los tramos
 * `original` y las de la voz sintetizada en los tramos `narracion`, todas con tiempos
 * relativos al inicio del clip.
 */
async function construirSubtitulos(
  videoId: string,
  clip: Clip,
  transcripcion: Transcripcion,
): Promise<Subtitulo[]> {
  const guion = await leerJson(rutas.guion(videoId, clip.indice), GuionSchema);
  const subtitulos: Subtitulo[] = [];

  const rutaNarracion = rutas.narracion(videoId, clip.indice);
  const narracion = (await existe(rutaNarracion))
    ? await leerJson(rutaNarracion, NarracionSchema)
    : { voz: "", tramos: [] };

  for (const [posicion, tramo] of guion.tramos.entries()) {
    if (tramo.tipo === "original") {
      for (const segmento of transcripcion.segmentos) {
        for (const palabra of segmento.palabras) {
          const relativo = palabra.inicio - clip.inicio;
          if (relativo < tramo.inicio || relativo >= tramo.fin) continue;
          subtitulos.push({
            texto: palabra.texto,
            inicio: relativo,
            fin: palabra.fin - clip.inicio,
            origen: "original",
          });
        }
      }
      continue;
    }

    const pista = narracion.tramos.find((t) => t.tramo === posicion);
    if (!pista) continue;
    for (const palabra of pista.palabras) {
      subtitulos.push({
        texto: palabra.texto,
        inicio: pista.desplazamiento + palabra.inicio,
        fin: pista.desplazamiento + palabra.fin,
        origen: "narracion",
      });
    }
  }

  return subtitulos.sort((a, b) => a.inicio - b.inicio);
}

async function renderizarClip(
  videoId: string,
  clip: Clip,
  transcripcion: Transcripcion,
  force: boolean,
): Promise<string> {
  const salida = rutas.final(videoId, clip.indice);

  return pasoIdempotente({
    salida,
    force,
    nombre: `render clip #${clip.indice}`,
    leer: async () => salida,
    calcular: async () => {
      if (!(await existe(rutas.base(videoId, clip.indice)))) {
        throw new Error(`Falta base.mp4 del clip #${clip.indice}. Ejecuta antes el paso "montar".`);
      }
      await verificarEspacio(config.mediaDir);

      const guion = await leerJson(rutas.guion(videoId, clip.indice), GuionSchema);
      const props: PropsClip = {
        // Ruta relativa al publicDir (= MEDIA_DIR), que es lo que resuelve staticFile().
        video: `${videoId}/clips/${clip.indice}/base.mp4`.replace(/\\/g, "/"),
        duracion: clip.fin - clip.inicio,
        fps: config.video.fps,
        hook: guion.hook,
        subtitulos: await construirSubtitulos(videoId, clip, transcripcion),
        ...(guion.parte !== undefined && guion.totalPartes !== undefined
          ? { parte: guion.parte, totalPartes: guion.totalPartes }
          : {}),
      };

      const serveUrl = await obtenerBundle();
      const composicion = await selectComposition({
        serveUrl,
        id: "ClipVertical",
        inputProps: props,
      });

      console.log(
        `· render #${clip.indice}: ${composicion.durationInFrames} frames ` +
          `(${props.subtitulos.length} palabras de subtítulo)…`,
      );

      await renderMedia({
        serveUrl,
        composition: composicion,
        codec: "h264",
        outputLocation: salida,
        inputProps: props,
        // El default de Remotion (crf 18, preset medium) produce archivos enormes y tarda el
        // doble. Con episodios de varios minutos eso son GB y horas; crf 23 es indistinguible
        // en un móvil.
        crf: config.renderCrf,
        x264Preset: config.renderPreset,
        ...(config.renderConcurrencia ? { concurrency: config.renderConcurrencia } : {}),
        onProgress: ({ progress }) => {
          process.stdout.write(`\r  ${Math.round(progress * 100)}%`);
        },
      });
      process.stdout.write("\r");

      await comprimirPreview(salida, rutas.preview(videoId, clip.indice));
      console.log(`  → ${salida}`);
      return salida;
    },
  });
}

export async function renderizarClips(
  videoId: string,
  opciones: OpcionesRender = {},
): Promise<string[]> {
  await leerJson(rutas.fuente(videoId), FuenteSchema);
  const { clips } = await leerJson(rutas.clips(videoId), ClipsSchema);
  const transcripcion = await leerJson(rutas.transcripcion(videoId), TranscripcionSchema);

  const seleccionados =
    opciones.clip === undefined ? clips : clips.filter((c) => c.indice === opciones.clip);
  if (seleccionados.length === 0) {
    throw new Error(`No existe el clip ${opciones.clip} en ${rutas.clips(videoId)}`);
  }

  // Un lote de episodios largos son horas de render: se comprueba el disco para el total, no
  // pieza a pieza, para no abortar a mitad de una serie.
  const pendientes: Clip[] = [];
  for (const clip of seleccionados) {
    if (opciones.force || !(await existe(rutas.final(videoId, clip.indice)))) pendientes.push(clip);
  }
  if (pendientes.length > 0) {
    await verificarEspacioParaSerie(
      config.mediaDir,
      pendientes.reduce((s, c) => s + (c.fin - c.inicio), 0),
    );
  }

  const salidas: string[] = [];
  for (const clip of seleccionados) {
    salidas.push(await renderizarClip(videoId, clip, transcripcion, opciones.force ?? false));
  }
  return salidas;
}
