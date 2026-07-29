/**
 * Único punto del proyecto donde se lanzan subprocesos (ffmpeg, ffprobe, python).
 * Centralizarlo permite que todos los errores externos lleguen con el mismo formato:
 * comando, código de salida y las últimas líneas de stderr, que es lo que de verdad
 * explica por qué falló ffmpeg.
 */

import { spawn } from "node:child_process";

export class ErrorProceso extends Error {
  constructor(
    readonly comando: string,
    readonly codigo: number | null,
    readonly stderr: string,
  ) {
    const cola = stderr.trim().split(/\r?\n/).slice(-12).join("\n");
    super(`El comando "${comando}" terminó con código ${codigo}.\n${cola}`);
    this.name = "ErrorProceso";
  }
}

export interface OpcionesEjecutar {
  /** Se llama con cada fragmento de stderr; útil para mostrar progreso de ffmpeg. */
  onStderr?: (fragmento: string) => void;
  cwd?: string;
  /** Etiqueta legible para los mensajes de error (por defecto, el nombre del binario). */
  etiqueta?: string;
}

export interface ResultadoProceso {
  stdout: string;
  stderr: string;
}

export function ejecutar(
  comando: string,
  args: string[],
  opciones: OpcionesEjecutar = {},
): Promise<ResultadoProceso> {
  const etiqueta = opciones.etiqueta ?? comando.split(/[\\/]/).pop() ?? comando;

  return new Promise((resolver, rechazar) => {
    const proc = spawn(comando, args, { cwd: opciones.cwd, windowsHide: true });

    let stdout = "";
    let stderr = "";

    proc.stdout.setEncoding("utf8");
    proc.stdout.on("data", (d: string) => {
      stdout += d;
    });

    proc.stderr.setEncoding("utf8");
    proc.stderr.on("data", (d: string) => {
      stderr += d;
      opciones.onStderr?.(d);
    });

    proc.on("error", (err) => {
      rechazar(new Error(`No se pudo ejecutar "${etiqueta}": ${err.message}`));
    });

    proc.on("close", (codigo) => {
      if (codigo === 0) resolver({ stdout, stderr });
      else rechazar(new ErrorProceso(etiqueta, codigo, stderr));
    });
  });
}

/**
 * Ejecuta un proceso cuyo stdout es JSON puro (los logs van a stderr).
 * Es el contrato de los scripts de `scripts/`.
 */
export async function ejecutarJson<T>(
  comando: string,
  args: string[],
  opciones: OpcionesEjecutar = {},
): Promise<T> {
  const { stdout } = await ejecutar(comando, args, opciones);
  try {
    return JSON.parse(stdout) as T;
  } catch {
    const muestra = stdout.slice(0, 400);
    throw new Error(
      `La salida de "${opciones.etiqueta ?? comando}" no es JSON válido. Primeros caracteres:\n${muestra}`,
    );
  }
}
