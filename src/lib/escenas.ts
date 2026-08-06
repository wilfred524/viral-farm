/**
 * Detección de cambios de plano, para que un episodio no empiece ni termine a mitad de una
 * escena.
 *
 * La detección se hace SOLO en ventanas cortas alrededor de los cortes que propone el LLM,
 * nunca sobre la película entera: analizar 6 segundos cuesta ~0,25 s, mientras que decodificar
 * una película de 86 minutos costaría minutos y casi todo el trabajo sería desechado.
 */

import { config } from "../config.js";
import { ejecutar } from "./proceso.js";

export interface OpcionesCortes {
  /** Radio de la ventana de búsqueda, en segundos. */
  ventana?: number;
  /** Umbral del filtro `scene`: 0.3 detecta corte duro sin dispararse con paneos rápidos. */
  umbral?: number;
}

const VENTANA = 3;
const UMBRAL = 0.3;
/**
 * Tras un seek, el primer frame decodificado puede reportarse como cambio de escena aunque no
 * lo sea. Se descarta lo que caiga pegado al borde inicial de la ventana.
 */
const MARGEN_BORDE = 0.15;

/**
 * Cambios de plano en `[instante-ventana, instante+ventana]`, en segundos absolutos del fuente
 * y ordenados por cercanía al instante pedido.
 */
export async function cortesCercanos(
  fuente: string,
  instante: number,
  opciones: OpcionesCortes = {},
): Promise<number[]> {
  const ventana = opciones.ventana ?? VENTANA;
  const umbral = opciones.umbral ?? UMBRAL;
  const desde = Math.max(0, instante - ventana);
  const duracion = instante - desde + ventana;

  // `-ss` antes de `-i` evita decodificar desde el principio del archivo; `-copyts` conserva
  // los timestamps del fuente, de modo que `pts_time` ya viene en segundos absolutos.
  const { stderr } = await ejecutar(
    config.ffmpeg,
    [
      "-hide_banner", "-nostats",
      "-ss", desde.toFixed(3),
      "-t", duracion.toFixed(3),
      "-copyts",
      "-i", fuente,
      "-an", "-sn",
      "-filter:v", `select='gt(scene,${umbral})',showinfo`,
      "-f", "null", "-",
    ],
    { etiqueta: "ffmpeg (escenas)" },
  );

  const cortes: number[] = [];
  for (const linea of stderr.split(/\r?\n/)) {
    const encontrado = linea.match(/pts_time:([0-9.]+)/);
    if (!encontrado) continue;
    const t = Number(encontrado[1]);
    if (!Number.isFinite(t) || t < desde + MARGEN_BORDE) continue;
    cortes.push(t);
  }

  return cortes.sort((a, b) => Math.abs(a - instante) - Math.abs(b - instante));
}

/**
 * Cortes alrededor de varios instantes. Secuencial a propósito: cada ventana cuesta décimas de
 * segundo y lanzar N ffmpeg a la vez compite con el resto del pipeline por CPU.
 */
export async function detectarCortes(
  fuente: string,
  instantes: number[],
  opciones: OpcionesCortes = {},
): Promise<Map<number, number[]>> {
  const mapa = new Map<number, number[]>();
  for (const instante of instantes) {
    if (mapa.has(instante)) continue;
    mapa.set(instante, await cortesCercanos(fuente, instante, opciones));
  }
  return mapa;
}
