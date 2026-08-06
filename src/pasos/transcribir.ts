/**
 * Paso 2 — Transcripción. Extrae el audio a WAV 16 kHz mono y lo pasa por faster-whisper
 * (local, coste cero). El resultado incluye timestamps por palabra: son la base de los
 * subtítulos karaoke y de la selección de clips ajustada a fronteras de frase.
 */

import path from "node:path";
import { config } from "../config.js";
import { TranscripcionSchema, type Transcripcion } from "../tipos.js";
import { extraerAudio } from "../lib/ffmpeg.js";
import { ejecutarJson } from "../lib/proceso.js";
import { escribirJson, existe, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";
import { FuenteSchema } from "../tipos.js";

export interface OpcionesTranscribir {
  force?: boolean;
  /** ISO 639-1 del audio, o `auto` para que lo detecte Whisper. Por defecto, la config. */
  idioma?: string;
}

export async function transcribir(
  videoId: string,
  opciones: OpcionesTranscribir = {},
): Promise<Transcripcion> {
  const fuente = await leerJson(rutas.fuente(videoId), FuenteSchema);
  const force = opciones.force ?? false;
  const idioma = opciones.idioma?.trim() || config.idiomaFuente;

  return pasoIdempotente({
    salida: rutas.transcripcion(videoId),
    force,
    nombre: "transcripción",
    leer: () => leerJson(rutas.transcripcion(videoId), TranscripcionSchema),
    calcular: async () => {
      const audio = rutas.audio(videoId);
      if (force || !(await existe(audio))) {
        console.log("· transcripción: extrayendo audio…");
        await extraerAudio(fuente.rutaOriginal, audio);
      }

      console.log(
        `· transcripción: faster-whisper (${config.modeloWhisper}, idioma ${idioma})…`,
      );
      const bruto = await ejecutarJson<unknown>(
        config.python,
        [
          path.join(config.scriptsDir, "transcribir.py"),
          "--audio", audio,
          "--modelo", config.modeloWhisper,
          "--idioma", idioma,
          "--dispositivo", config.dispositivoWhisper,
        ],
        {
          etiqueta: "faster-whisper",
          // Whisper tarda minutos: mostrar cada segmento conforme aparece da señal de vida.
          onStderr: (fragmento) => process.stderr.write(fragmento),
        },
      );

      const transcripcion = await escribirJson(
        rutas.transcripcion(videoId),
        TranscripcionSchema,
        bruto as Transcripcion,
      );

      const palabras = transcripcion.segmentos.reduce((n, s) => n + s.palabras.length, 0);
      if (palabras === 0) {
        throw new Error(
          "La transcripción no trae timestamps por palabra. Revisa que el script use word_timestamps=True.",
        );
      }
      console.log(
        `· transcripción: ${transcripcion.segmentos.length} segmentos, ${palabras} palabras (${transcripcion.idioma})`,
      );
      return transcripcion;
    },
  });
}
