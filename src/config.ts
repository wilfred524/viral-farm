/**
 * Configuración del pipeline: resuelve rutas y binarios externos, y falla temprano con un
 * mensaje accionable cuando falta algo (una clave de API o ffmpeg ausente debe romper antes
 * de gastar minutos de transcripción o render).
 */

import { existsSync } from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

const RAIZ = path.resolve(import.meta.dirname, "..");

/** Busca un binario en PATH; devuelve null si no existe. */
function buscarEnPath(binario: string): string | null {
  try {
    const salida = execFileSync(process.platform === "win32" ? "where" : "which", [binario], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    const primera = salida.split(/\r?\n/).find((l) => l.trim().length > 0);
    return primera ? primera.trim() : null;
  } catch {
    return null;
  }
}

function resolverFfmpeg(): string {
  const declarado = process.env.FFMPEG_PATH?.trim();
  if (declarado) {
    if (!existsSync(declarado)) {
      throw new Error(`FFMPEG_PATH apunta a un archivo inexistente: ${declarado}`);
    }
    return declarado;
  }
  const enPath = buscarEnPath("ffmpeg");
  if (!enPath) {
    throw new Error(
      "No se encontró ffmpeg. Instálalo o define FFMPEG_PATH en .env.\n" +
        "Aviso: el ffmpeg que trae Remotion es un build mínimo y no sirve para este pipeline.",
    );
  }
  return enPath;
}

function resolverFfprobe(ffmpeg: string): string {
  const vecino = path.join(path.dirname(ffmpeg), process.platform === "win32" ? "ffprobe.exe" : "ffprobe");
  if (existsSync(vecino)) return vecino;
  const enPath = buscarEnPath("ffprobe");
  if (!enPath) throw new Error("No se encontró ffprobe (suele venir junto a ffmpeg).");
  return enPath;
}

function resolverPython(): string {
  const declarado = process.env.PYTHON_PATH?.trim();
  if (declarado) return declarado;
  return buscarEnPath("python") ?? buscarEnPath("python3") ?? "python";
}

const ffmpeg = resolverFfmpeg();

export const config = {
  raiz: RAIZ,
  mediaDir: path.resolve(RAIZ, process.env.MEDIA_DIR?.trim() || "media"),
  scriptsDir: path.join(RAIZ, "scripts"),
  remotionDir: path.join(RAIZ, "remotion"),
  ffmpeg,
  ffprobe: resolverFfprobe(ffmpeg),
  python: resolverPython(),

  /** Modelo de Whisper para faster-whisper (tiny/base/small/medium/large-v3). */
  modeloWhisper: process.env.WHISPER_MODELO?.trim() || "small",
  idiomaWhisper: process.env.WHISPER_IDIOMA?.trim() || "es",
  /** cpu | cuda. Con `cuda` hacen falta las libs de cuBLAS/cuDNN instaladas. */
  dispositivoWhisper: process.env.WHISPER_DISPOSITIVO?.trim() || "cpu",

  /** Voz de Edge-TTS. `edge-tts --list-voices` lista las disponibles. */
  vozTts: process.env.TTS_VOZ?.trim() || "es-MX-JorgeNeural",

  modeloLlm: process.env.LLM_MODELO?.trim() || "claude-sonnet-5",

  /** Formato de salida vertical. */
  video: { ancho: 1080, alto: 1920, fps: 30 },

  /** Atenuación del audio ambiental bajo la narración, en dB. */
  duckingDb: Number(process.env.DUCKING_DB ?? -18),

  /** Espacio libre mínimo antes de renderizar (los renders fallan con errores confusos si el disco se llena). */
  minGbLibres: Number(process.env.MIN_GB_LIBRES ?? 8),
} as const;

export function requiereClaveAnthropic(): string {
  const clave = process.env.ANTHROPIC_API_KEY?.trim();
  if (!clave) {
    throw new Error("Falta ANTHROPIC_API_KEY. Copia .env.example a .env y complétala.");
  }
  return clave;
}
