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
