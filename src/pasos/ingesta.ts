/**
 * Paso 1 — Ingesta: valida el video fuente, lo describe con ffprobe y crea su carpeta de
 * trabajo. A partir de aquí todo el pipeline se refiere al video por su `videoId`.
 */

import { createHash } from "node:crypto";
import path from "node:path";
import { stat } from "node:fs/promises";
import { FuenteSchema, type Fuente } from "../tipos.js";
import { probe } from "../lib/ffmpeg.js";
import { asegurarDir, dirVideo, escribirJson, existe, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";

const EXTENSIONES = new Set([".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".ts"]);

/** Identificador estable y legible: nombre del archivo + hash de su ruta y tamaño. */
function generarVideoId(ruta: string, tamano: number): string {
  const base = path
    .basename(ruta, path.extname(ruta))
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  const hash = createHash("sha1").update(`${path.resolve(ruta)}:${tamano}`).digest("hex").slice(0, 8);
  return `${base || "video"}-${hash}`;
}

export async function ingestar(rutaVideo: string, force = false): Promise<Fuente> {
  const ruta = path.resolve(rutaVideo);
  if (!(await existe(ruta))) {
    throw new Error(`No existe el video fuente: ${ruta}`);
  }

  const extension = path.extname(ruta).toLowerCase();
  if (!EXTENSIONES.has(extension)) {
    throw new Error(
      `Extensión no soportada: ${extension}. Soportadas: ${[...EXTENSIONES].join(", ")}`,
    );
  }

  const info = await stat(ruta);
  const videoId = generarVideoId(ruta, info.size);
  await asegurarDir(dirVideo(videoId));

  return pasoIdempotente({
    salida: rutas.fuente(videoId),
    force,
    nombre: `ingesta (${videoId})`,
    leer: () => leerJson(rutas.fuente(videoId), FuenteSchema),
    calcular: async () => {
      const medio = await probe(ruta);
      if (!medio.codecAudio) {
        throw new Error(
          "El video no tiene pista de audio: sin audio no hay transcripción ni clips que seleccionar.",
        );
      }
      const fuente: Fuente = {
        videoId,
        rutaOriginal: ruta,
        duracion: medio.duracion,
        ancho: medio.ancho,
        alto: medio.alto,
        fps: medio.fps,
        rotacion: medio.rotacion,
        codecVideo: medio.codecVideo,
        codecAudio: medio.codecAudio,
        creadoEn: new Date().toISOString(),
      };
      await escribirJson(rutas.fuente(videoId), FuenteSchema, fuente);
      console.log(
        `· ingesta: ${videoId} — ${medio.ancho}×${medio.alto}` +
          (medio.rotacion ? ` (rotación ${medio.rotacion}°)` : "") +
          `, ${medio.duracion.toFixed(1)} s, ${medio.codecVideo}/${medio.codecAudio}`,
      );
      return fuente;
    },
  });
}
