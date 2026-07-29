/**
 * ViralFarm CLI — Fase 1.
 *
 * Pipeline manual end-to-end: video largo → transcripción → selección de clips → guion →
 * TTS → montaje vertical con ducking → render con subtítulos.
 *
 * Uso: npm run cli -- <comando> [opciones]
 *
 * Cada paso es idempotente: si su artefacto ya existe se omite, salvo que se pase --force.
 * Los pasos se importan de forma diferida para que un comando no cargue (ni exija las claves
 * de) los módulos que no necesita.
 */

import { parsearOpciones, requiereVideoId, type OpcionesCli } from "./lib/args.js";

const AYUDA = `ViralFarm CLI (Fase 1)

Comandos:
  ingest <video>      Registra el video fuente y crea su carpeta de trabajo
  transcribe          Transcribe el audio con faster-whisper (timestamps por palabra)
  clips               El LLM selecciona los fragmentos con más gancho
  guion               Genera hook, tramos narración/original, caption y hashtags por clip
  tts                 Sintetiza la narración con Edge-TTS
  montar              Recorta, reencuadra a 9:16 y mezcla el audio (ducking)
  render              Monta subtítulos y plantilla con Remotion → final.mp4
  run <video>         Ejecuta todo el pipeline de principio a fin
  help                Muestra esta ayuda

Opciones:
  --video-id <id>     Video sobre el que operar (lo imprime \`ingest\`)
  --n <numero>        Número de clips a extraer (por defecto 5)
  --clip <indice>     Limita el paso a un solo clip
  --sin-tts           No genera narración: los clips conservan solo su audio original
  --reencuadre <m>    center (recorte central, por defecto) | blur-pad (fondo desenfocado)
  --force             Rehace el paso aunque su artefacto ya exista
`;

type Manejador = (opciones: OpcionesCli) => Promise<void>;

const comandos: Record<string, Manejador> = {
  async ingest(opciones) {
    const [video] = opciones.posicionales;
    if (!video) throw new Error("Uso: ingest <ruta-del-video>");
    const { ingestar } = await import("./pasos/ingesta.js");
    const fuente = await ingestar(video, opciones.force);
    console.log(`\nvideo-id: ${fuente.videoId}`);
  },

  async transcribe(opciones) {
    const { transcribir } = await import("./pasos/transcribir.js");
    await transcribir(requiereVideoId(opciones), opciones.force);
  },

  async clips(opciones) {
    const { seleccionarClips } = await import("./pasos/clips.js");
    await seleccionarClips(requiereVideoId(opciones), opciones.n, opciones.force);
  },

  async guion(opciones) {
    const { generarGuiones } = await import("./pasos/guion.js");
    await generarGuiones(requiereVideoId(opciones), {
      force: opciones.force,
      clip: opciones.clip,
      sinTts: opciones.sinTts,
    });
  },

  async tts(opciones) {
    if (opciones.sinTts) {
      console.log("· tts: omitido por --sin-tts");
      return;
    }
    const { sintetizarNarraciones } = await import("./pasos/tts.js");
    await sintetizarNarraciones(requiereVideoId(opciones), {
      force: opciones.force,
      clip: opciones.clip,
    });
  },

  async montar(opciones) {
    const { montarClips } = await import("./pasos/montaje.js");
    await montarClips(requiereVideoId(opciones), {
      force: opciones.force,
      clip: opciones.clip,
      reencuadre: opciones.reencuadre,
      sinTts: opciones.sinTts,
    });
  },

  async render(opciones) {
    const { renderizarClips } = await import("./pasos/render.js");
    await renderizarClips(requiereVideoId(opciones), {
      force: opciones.force,
      clip: opciones.clip,
    });
  },

  async run(opciones) {
    const [video] = opciones.posicionales;
    if (!video) throw new Error("Uso: run <ruta-del-video>");
    const { ejecutarPipeline } = await import("./pasos/pipeline.js");
    await ejecutarPipeline(video, opciones);
  },

  async help() {
    console.log(AYUDA);
  },
};

async function principal(): Promise<void> {
  const [comando = "help", ...resto] = process.argv.slice(2);

  const manejador = comandos[comando];
  if (!manejador) {
    console.error(`Comando desconocido: ${comando}. Usa "help" para ver los disponibles.`);
    process.exit(1);
  }

  const opciones = parsearOpciones(resto);
  await manejador(opciones);
}

principal().catch((error: unknown) => {
  console.error(`\n✖ ${error instanceof Error ? error.message : String(error)}`);
  process.exit(1);
});
