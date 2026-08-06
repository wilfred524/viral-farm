/**
 * Todas las operaciones de video del pipeline.
 *
 * Se usa siempre el ffmpeg completo del sistema (`config.ffmpeg`), nunca el que trae
 * Remotion: ese es un build mínimo sin `loudnorm`, `gblur` ni `subtitles`.
 */

import { config } from "../config.js";
import { ejecutar, ejecutarJson } from "./proceso.js";
import { asegurarDir } from "./artefactos.js";
import path from "node:path";

export type Reencuadre = "center" | "blur-pad";

export interface InfoMedio {
  duracion: number;
  ancho: number;
  alto: number;
  fps: number;
  rotacion: number;
  codecVideo: string;
  codecAudio: string | null;
}

interface FlujoProbe {
  codec_type?: string;
  codec_name?: string;
  width?: number;
  height?: number;
  avg_frame_rate?: string;
  r_frame_rate?: string;
  duration?: string;
  tags?: { rotate?: string };
  side_data_list?: { rotation?: number }[];
}

interface SalidaProbe {
  streams?: FlujoProbe[];
  format?: { duration?: string };
}

function fraccionAFps(fraccion: string | undefined): number {
  if (!fraccion) return 0;
  const [num, den] = fraccion.split("/").map(Number);
  if (!num || !den) return 0;
  return num / den;
}

export async function probe(ruta: string): Promise<InfoMedio> {
  const datos = await ejecutarJson<SalidaProbe>(
    config.ffprobe,
    ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", ruta],
    { etiqueta: "ffprobe" },
  );

  const video = datos.streams?.find((s) => s.codec_type === "video");
  const audio = datos.streams?.find((s) => s.codec_type === "audio");
  if (!video) throw new Error(`El archivo no contiene pista de video: ${ruta}`);

  const duracion = Number(datos.format?.duration ?? video.duration ?? 0);
  if (!duracion) throw new Error(`No se pudo determinar la duración de ${ruta}`);

  // La rotación puede venir en tags (contenedores antiguos) o en side_data (MOV de móvil).
  const rotacionSideData = video.side_data_list?.find((s) => s.rotation !== undefined)?.rotation;
  const rotacion = Number(rotacionSideData ?? video.tags?.rotate ?? 0);

  return {
    duracion,
    ancho: video.width ?? 0,
    alto: video.height ?? 0,
    fps: fraccionAFps(video.avg_frame_rate) || fraccionAFps(video.r_frame_rate) || 0,
    rotacion,
    codecVideo: video.codec_name ?? "desconocido",
    codecAudio: audio?.codec_name ?? null,
  };
}

export async function duracionMedio(ruta: string): Promise<number> {
  const datos = await ejecutarJson<SalidaProbe>(
    config.ffprobe,
    ["-v", "error", "-print_format", "json", "-show_format", ruta],
    { etiqueta: "ffprobe" },
  );
  const duracion = Number(datos.format?.duration ?? 0);
  if (!duracion) throw new Error(`No se pudo determinar la duración de ${ruta}`);
  return duracion;
}

/** Extrae el audio a WAV 16 kHz mono, que es lo que espera Whisper. */
export async function extraerAudio(entrada: string, salida: string): Promise<void> {
  await asegurarDir(path.dirname(salida));
  await ejecutar(
    config.ffmpeg,
    ["-y", "-i", entrada, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", salida],
    { etiqueta: "ffmpeg (extraer audio)" },
  );
}

// === construcción del clip base ===

/** Convierte dB a factor lineal de amplitud. */
function dbAFactor(db: number): number {
  return 10 ** (db / 20);
}

/**
 * Expresión de volumen del audio ambiental a lo largo del clip.
 *
 * Vale 1 fuera de los tramos narrados y `factor` dentro, con rampas de `rampa` segundos en
 * cada frontera para que la atenuación no suene como un salto brusco.
 */
function expresionDucking(
  tramos: { inicio: number; fin: number }[],
  factor: number,
  rampa = 0.25,
): string {
  if (tramos.length === 0) return "1";
  // Cada tramo aporta una rampa trapezoidal entre 0 y 1; se toma la mayor de todas.
  const trapecios = tramos.map(({ inicio, fin }) => {
    const subida = Math.max(inicio - rampa, 0);
    const bajada = fin + rampa;
    return `min(1,max(0,min((t-${subida.toFixed(3)})/${rampa},(${bajada.toFixed(3)}-t)/${rampa})))`;
  });
  const combinado = trapecios.reduce((acc, t) => (acc ? `max(${acc},${t})` : t), "");
  return `1-${(1 - factor).toFixed(4)}*(${combinado})`;
}

export interface NarracionEnMezcla {
  /** Ruta del mp3 generado por el TTS. */
  archivo: string;
  /** Segundo del clip en el que debe empezar a sonar. */
  desplazamiento: number;
  /** Factor `atempo` a aplicar (1 = sin cambio). */
  tempo: number;
}

export interface OpcionesBase {
  fuente: string;
  inicio: number;
  duracion: number;
  reencuadre: Reencuadre;
  /** Tramos del clip (relativos a su inicio) donde suena narración. */
  tramosNarrados: { inicio: number; fin: number }[];
  narraciones: NarracionEnMezcla[];
  salida: string;
  onProgreso?: (linea: string) => void;
}

function filtroVideo(reencuadre: Reencuadre): string {
  const { ancho, alto, fps } = config.video;
  if (reencuadre === "center") {
    // Escala cubriendo el marco vertical y recorta el centro: nunca deforma.
    return (
      `[0:v]scale=${ancho}:${alto}:force_original_aspect_ratio=increase,` +
      `crop=${ancho}:${alto},fps=${fps},setsar=1[v]`
    );
  }
  // Fondo desenfocado a pantalla completa + el original contenido y centrado encima.
  return (
    `[0:v]split=2[bg][fg];` +
    `[bg]scale=${ancho}:${alto}:force_original_aspect_ratio=increase,crop=${ancho}:${alto},gblur=sigma=30[bgb];` +
    `[fg]scale=${ancho}:${alto}:force_original_aspect_ratio=decrease[fgs];` +
    `[bgb][fgs]overlay=(W-w)/2:(H-h)/2,fps=${fps},setsar=1[v]`
  );
}

/**
 * Recorta el fragmento, lo lleva a vertical y mezcla el audio ambiental con la narración
 * (ducking). Todo en un solo pase de ffmpeg para no acumular pérdidas de recodificación.
 */
export async function construirBase(opciones: OpcionesBase): Promise<void> {
  const { ancho, alto, fps } = config.video;
  await asegurarDir(path.dirname(opciones.salida));

  const args: string[] = [
    "-y",
    "-ss", opciones.inicio.toFixed(3),
    "-t", opciones.duracion.toFixed(3),
    "-i", opciones.fuente,
  ];
  for (const narracion of opciones.narraciones) {
    args.push("-i", narracion.archivo);
  }

  const cadenas: string[] = [filtroVideo(opciones.reencuadre)];

  const ducking = expresionDucking(opciones.tramosNarrados, dbAFactor(config.duckingDb));
  cadenas.push(
    `[0:a]aresample=48000,volume=volume='${ducking}':eval=frame,` +
      `apad=whole_dur=${opciones.duracion.toFixed(3)}[amb]`,
  );

  const etiquetasMezcla = ["[amb]"];
  opciones.narraciones.forEach((narracion, i) => {
    const entrada = i + 1;
    const retrasoMs = Math.round(narracion.desplazamiento * 1000);
    const tempo = narracion.tempo !== 1 ? `atempo=${narracion.tempo.toFixed(4)},` : "";
    cadenas.push(
      `[${entrada}:a]aresample=48000,${tempo}adelay=${retrasoMs}|${retrasoMs}[n${i}]`,
    );
    etiquetasMezcla.push(`[n${i}]`);
  });

  if (etiquetasMezcla.length > 1) {
    cadenas.push(
      `${etiquetasMezcla.join("")}amix=inputs=${etiquetasMezcla.length}:normalize=0:duration=first[mezcla]`,
    );
    cadenas.push(`[mezcla]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]`);
  } else {
    cadenas.push(`[amb]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]`);
  }

  args.push(
    "-filter_complex", cadenas.join(";"),
    "-map", "[v]",
    "-map", "[a]",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "20",
    "-pix_fmt", "yuv420p",
    // Un keyframe por segundo: `OffthreadVideo` extrae cada frame por seek, y con GOP largo
    // cada seek obliga a decodificar desde el keyframe anterior. Sube algo el tamaño de
    // base.mp4 (que es intermedio) a cambio de acelerar el render, que es lo caro.
    "-g", String(fps),
    "-keyint_min", String(fps),
    "-r", String(fps),
    "-s", `${ancho}x${alto}`,
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "48000",
    "-movflags", "+faststart",
    opciones.salida,
  );

  await ejecutar(config.ffmpeg, args, {
    etiqueta: "ffmpeg (montaje)",
    onStderr: opciones.onProgreso,
  });
}

/** Recomprime a un archivo pequeño para el preview de Telegram (límite de 50 MB de la Bot API). */
export async function comprimirPreview(entrada: string, salida: string): Promise<void> {
  await asegurarDir(path.dirname(salida));
  await ejecutar(
    config.ffmpeg,
    [
      "-y", "-i", entrada,
      "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
      "-vf", "scale=720:1280",
      "-c:a", "aac", "-b:a", "96k",
      "-movflags", "+faststart",
      salida,
    ],
    { etiqueta: "ffmpeg (preview)" },
  );
}
