/**
 * Parser mínimo de argumentos del CLI. Node 24 trae `util.parseArgs`; este módulo solo le
 * añade tipado y mensajes de error en español para las opciones que usa el pipeline.
 */

import { parseArgs } from "node:util";

export interface OpcionesCli {
  videoId?: string;
  force: boolean;
  n: number;
  sinTts: boolean;
  reencuadre: "center" | "blur-pad";
  clip?: number;
  posicionales: string[];
}

const REENCUADRES = ["center", "blur-pad"] as const;

export function parsearOpciones(argv: string[]): OpcionesCli {
  const { values, positionals } = parseArgs({
    args: argv,
    allowPositionals: true,
    options: {
      "video-id": { type: "string" },
      force: { type: "boolean", default: false },
      n: { type: "string", default: "5" },
      "sin-tts": { type: "boolean", default: false },
      reencuadre: { type: "string", default: "center" },
      clip: { type: "string" },
    },
  });

  const n = Number(values.n);
  if (!Number.isInteger(n) || n < 1 || n > 20) {
    throw new Error(`--n debe ser un entero entre 1 y 20 (recibido: ${values.n})`);
  }

  const reencuadre = values.reencuadre as (typeof REENCUADRES)[number];
  if (!REENCUADRES.includes(reencuadre)) {
    throw new Error(`--reencuadre debe ser uno de: ${REENCUADRES.join(", ")}`);
  }

  let clip: number | undefined;
  if (values.clip !== undefined) {
    clip = Number(values.clip);
    if (!Number.isInteger(clip) || clip < 0) {
      throw new Error(`--clip debe ser un índice entero (recibido: ${values.clip})`);
    }
  }

  return {
    videoId: values["video-id"],
    force: values.force ?? false,
    n,
    sinTts: values["sin-tts"] ?? false,
    reencuadre,
    clip,
    posicionales: positionals,
  };
}

/** Devuelve el videoId de las opciones o falla con un mensaje útil. */
export function requiereVideoId(opciones: OpcionesCli): string {
  if (!opciones.videoId) {
    throw new Error("Falta --video-id. Lo imprime el comando `ingest`.");
  }
  return opciones.videoId;
}
