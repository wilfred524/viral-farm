/**
 * Rutas canónicas de los artefactos y lectura/escritura validada con Zod.
 *
 * La idempotencia del pipeline vive aquí: un paso pregunta si su artefacto ya existe y se
 * salta el trabajo salvo que se pase `--force`. Así se puede reintentar cualquier punto del
 * pipeline sin repetir transcripciones ni llamadas al LLM ya pagadas.
 */

import { mkdir, readFile, writeFile, access } from "node:fs/promises";
import path from "node:path";
import type { z } from "zod";
import { config } from "../config.js";

export function dirVideo(videoId: string): string {
  return path.join(config.mediaDir, videoId);
}

export function dirClip(videoId: string, indice: number): string {
  return path.join(dirVideo(videoId), "clips", String(indice));
}

export const rutas = {
  fuente: (v: string) => path.join(dirVideo(v), "fuente.json"),
  audio: (v: string) => path.join(dirVideo(v), "audio.wav"),
  transcripcion: (v: string) => path.join(dirVideo(v), "transcripcion.json"),
  clips: (v: string) => path.join(dirVideo(v), "clips.json"),
  guion: (v: string, i: number) => path.join(dirClip(v, i), "guion.json"),
  narracion: (v: string, i: number) => path.join(dirClip(v, i), "narracion.json"),
  dirNarracion: (v: string, i: number) => path.join(dirClip(v, i), "narracion"),
  base: (v: string, i: number) => path.join(dirClip(v, i), "base.mp4"),
  final: (v: string, i: number) => path.join(dirClip(v, i), "final.mp4"),
  preview: (v: string, i: number) => path.join(dirClip(v, i), "preview.mp4"),
} as const;

export async function existe(ruta: string): Promise<boolean> {
  try {
    await access(ruta);
    return true;
  } catch {
    return false;
  }
}

export async function asegurarDir(dir: string): Promise<void> {
  await mkdir(dir, { recursive: true });
}

export async function leerJson<T extends z.ZodTypeAny>(
  ruta: string,
  esquema: T,
): Promise<z.infer<T>> {
  let crudo: string;
  try {
    crudo = await readFile(ruta, "utf8");
  } catch {
    throw new Error(`Falta el artefacto ${path.relative(config.mediaDir, ruta)}. Ejecuta antes el paso que lo genera.`);
  }
  const resultado = esquema.safeParse(JSON.parse(crudo));
  if (!resultado.success) {
    throw new Error(
      `El artefacto ${path.relative(config.mediaDir, ruta)} no cumple su esquema:\n` +
        resultado.error.issues.map((i) => `  · ${i.path.join(".")}: ${i.message}`).join("\n"),
    );
  }
  return resultado.data;
}

export async function escribirJson<T extends z.ZodTypeAny>(
  ruta: string,
  esquema: T,
  datos: z.infer<T>,
): Promise<z.infer<T>> {
  const resultado = esquema.safeParse(datos);
  if (!resultado.success) {
    throw new Error(
      `Se intentó escribir ${path.basename(ruta)} con datos inválidos:\n` +
        resultado.error.issues.map((i) => `  · ${i.path.join(".")}: ${i.message}`).join("\n"),
    );
  }
  await asegurarDir(path.dirname(ruta));
  await writeFile(ruta, JSON.stringify(resultado.data, null, 2), "utf8");
  return resultado.data;
}

/**
 * Envuelve un paso con la política de idempotencia: si la salida existe y no hay `force`,
 * devuelve lo ya calculado.
 */
export async function pasoIdempotente<T>(opciones: {
  salida: string;
  force: boolean;
  nombre: string;
  leer: () => Promise<T>;
  calcular: () => Promise<T>;
}): Promise<T> {
  if (!opciones.force && (await existe(opciones.salida))) {
    console.log(`· ${opciones.nombre}: ya existe, se omite (usa --force para rehacerlo)`);
    return opciones.leer();
  }
  return opciones.calcular();
}
