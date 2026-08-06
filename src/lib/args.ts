/**
 * Parser mínimo de argumentos del CLI. Node 24 trae `util.parseArgs`; este módulo solo le
 * añade tipado y mensajes de error en español para las opciones que usa el pipeline.
 */

import { parseArgs } from "node:util";

export interface OpcionesCli {
  videoId?: string;
  force: boolean;
  n: number;
  /** true si el usuario pasó --n. Sin él, el formato serie deriva el tope de la duración. */
  nExplicito: boolean;
  sinTts: boolean;
  reencuadre: "center" | "blur-pad";
  clip?: number;
  /** Idioma hablado en el video; `auto` deja que lo detecte Whisper. */
  idioma?: string;
  /** Idioma de narración, hook y caption; sin valor, hereda del detectado. */
  idiomaSalida?: string;
  /** `serie` (episodios encadenados) o `virales` (fragmentos sueltos, formato legado). */
  formato: "serie" | "virales";
  /** Salta la detección de cambios de plano: los cortes se ajustan solo a frontera de frase. */
  sinEscenas: boolean;
  /** Instante del fuente, en segundos (comando `cortes`). */
  en?: number;
  posicionales: string[];
}

const REENCUADRES = ["center", "blur-pad"] as const;
const FORMATOS = ["serie", "virales"] as const;

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
      idioma: { type: "string" },
      "idioma-salida": { type: "string" },
      formato: { type: "string", default: "serie" },
      "sin-escenas": { type: "boolean", default: false },
      en: { type: "string" },
    },
  });

  // En formato serie `--n` es un tope, no una cantidad: una película larga da decenas de
  // episodios, así que el rango va mucho más allá de los 5 clips del formato viral.
  const n = Number(values.n);
  if (!Number.isInteger(n) || n < 1 || n > 60) {
    throw new Error(`--n debe ser un entero entre 1 y 60 (recibido: ${values.n})`);
  }

  const formato = values.formato as (typeof FORMATOS)[number];
  if (!FORMATOS.includes(formato)) {
    throw new Error(`--formato debe ser uno de: ${FORMATOS.join(", ")}`);
  }

  let en: number | undefined;
  if (values.en !== undefined) {
    en = Number(values.en);
    if (!Number.isFinite(en) || en < 0) {
      throw new Error(`--en debe ser un instante en segundos (recibido: ${values.en})`);
    }
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
    nExplicito: argv.some((a) => a === "--n" || a.startsWith("--n=")),
    sinTts: values["sin-tts"] ?? false,
    reencuadre,
    clip,
    idioma: values.idioma,
    idiomaSalida: values["idioma-salida"],
    formato,
    sinEscenas: values["sin-escenas"] ?? false,
    en,
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
