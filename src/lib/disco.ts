/**
 * Comprobación de espacio libre antes de operaciones que escriben mucho.
 *
 * Aprendizaje heredado del proyecto `my-video`: cuando el disco se llena, los renders de
 * Remotion fallan con errores que no mencionan el disco ("Failed to fetch", 500). Abortar
 * antes con un mensaje claro ahorra mucho tiempo de diagnóstico.
 */

import { statfs } from "node:fs/promises";
import { config } from "../config.js";

const BYTES_POR_GB = 1024 ** 3;

export async function gbLibres(ruta: string): Promise<number> {
  const info = await statfs(ruta);
  return (Number(info.bavail) * Number(info.bsize)) / BYTES_POR_GB;
}

/**
 * Megas que ocupa un segundo de pieza terminada, sumando `final.mp4` y `preview.mp4`. Medido
 * sobre renders reales a 1080×1920; con crf 23 el valor real queda por debajo, así que la
 * estimación es conservadora, que es lo que se quiere.
 */
const MB_POR_SEGUNDO = 0.9;

/**
 * Comprueba de una vez el espacio para toda una serie, antes de empezar.
 *
 * Con episodios de varios minutos un render completo dura horas: quedarse sin disco en el
 * episodio 9 de 11 deja una serie inservible y tira todo el tiempo invertido. Es preferible
 * fallar en el segundo cero.
 */
export async function verificarEspacioParaSerie(
  ruta: string,
  segundosTotales: number,
): Promise<void> {
  const necesarios = (segundosTotales * MB_POR_SEGUNDO) / 1024;
  const libres = await gbLibres(ruta);
  const margen = libres - necesarios;
  if (margen < config.minGbLibres) {
    throw new Error(
      `Espacio insuficiente para renderizar ${(segundosTotales / 60).toFixed(1)} minutos de ` +
        `episodios: hacen falta ~${necesarios.toFixed(1)} GB y solo hay ${libres.toFixed(1)} GB ` +
        `libres (umbral de seguridad: ${config.minGbLibres} GB).\n` +
        "Libera espacio, renderiza por partes con --clip, o baja MIN_GB_LIBRES en .env.",
    );
  }
  console.log(
    `· disco: ~${necesarios.toFixed(1)} GB estimados, ${libres.toFixed(1)} GB libres.`,
  );
}

export async function verificarEspacio(ruta: string, minGb = config.minGbLibres): Promise<void> {
  const libres = await gbLibres(ruta);
  if (libres < minGb) {
    throw new Error(
      `Espacio insuficiente en el volumen de ${ruta}: ${libres.toFixed(1)} GB libres, ` +
        `se requieren al menos ${minGb} GB.\n` +
        "Libera espacio o baja el umbral con MIN_GB_LIBRES en .env (bajo tu responsabilidad: " +
        "los renders fallan con errores confusos cuando el disco se llena).",
    );
  }
}
