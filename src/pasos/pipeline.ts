/**
 * Encadena los pasos de la Fase 1: video largo → clips verticales listos para aprobación.
 *
 * Cada paso es idempotente, así que reejecutar `run` tras un fallo retoma donde se quedó sin
 * repetir transcripciones ni llamadas al LLM ya pagadas.
 */

import { ingestar } from "./ingesta.js";
import { transcribir } from "./transcribir.js";
import { seleccionarClips } from "./clips.js";
import { generarGuiones } from "./guion.js";
import { sintetizarNarraciones } from "./tts.js";
import { montarClips } from "./montaje.js";
import { renderizarClips } from "./render.js";
import { uso } from "../lib/llm.js";
import type { OpcionesCli } from "../lib/args.js";
import { dirVideo } from "../lib/artefactos.js";

export async function ejecutarPipeline(rutaVideo: string, opciones: OpcionesCli): Promise<void> {
  const arranque = Date.now();

  console.log("\n[1/7] Ingesta");
  const fuente = await ingestar(rutaVideo, opciones.force);
  const videoId = fuente.videoId;

  console.log("\n[2/7] Transcripción");
  await transcribir(videoId, { force: opciones.force, idioma: opciones.idioma });

  console.log(`\n[3/7] ${opciones.formato === "serie" ? "Serie de episodios" : "Selección de clips"}`);
  await seleccionarClips(videoId, {
    n: opciones.nExplicito ? opciones.n : undefined,
    force: opciones.force,
    idiomaSalida: opciones.idiomaSalida,
    formato: opciones.formato,
    sinEscenas: opciones.sinEscenas,
  });

  console.log("\n[4/7] Guion");
  await generarGuiones(videoId, {
    force: opciones.force,
    clip: opciones.clip,
    sinTts: opciones.sinTts,
    idiomaSalida: opciones.idiomaSalida,
  });

  if (opciones.sinTts) {
    console.log("\n[5/7] Voz — omitida (--sin-tts)");
  } else {
    console.log("\n[5/7] Voz");
    await sintetizarNarraciones(videoId, { force: opciones.force, clip: opciones.clip });
  }

  console.log("\n[6/7] Montaje");
  await montarClips(videoId, {
    force: opciones.force,
    clip: opciones.clip,
    reencuadre: opciones.reencuadre,
    sinTts: opciones.sinTts,
  });

  console.log("\n[7/7] Render");
  const finales = await renderizarClips(videoId, { force: opciones.force, clip: opciones.clip });

  const minutos = (Date.now() - arranque) / 60000;
  console.log(`\n✔ ${finales.length} clips listos en ${dirVideo(videoId)}`);
  console.log(`  Tiempo total: ${minutos.toFixed(1)} min`);
  console.log(`  Tokens LLM: ${uso.entrada} entrada / ${uso.salida} salida`);
  console.log(`  video-id: ${videoId}`);
}
