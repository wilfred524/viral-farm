/**
 * Catálogo de idiomas del pipeline.
 *
 * Hay dos idiomas en juego y NO tienen por qué coincidir:
 * - **idioma fuente**: el que se habla en el video. Lo detecta Whisper (`auto`) o se fuerza.
 * - **idioma de salida**: en el que se escriben narración, hook, caption y hashtags. Por
 *   defecto hereda del fuente; se cambia para producir contenido en otro mercado (una
 *   película en inglés narrada en español, por ejemplo).
 *
 * Cada idioma aporta además la voz de Edge-TTS y su ritmo de habla, que es lo que decide
 * cuánto texto cabe en un tramo narrado.
 */

/** Voz multilingüe: sirve de red para cualquier idioma que no esté en el catálogo. */
const VOZ_FALLBACK = "en-US-AndrewMultilingualNeural";

export interface Idioma {
  /** Código ISO 639-1 en minúsculas. */
  codigo: string;
  /** Nombre en español, para los prompts del LLM. */
  nombre: string;
  /** Voz de Edge-TTS por defecto (`edge-tts --list-voices` lista el resto). */
  voz: string;
  /** Ritmo de habla de esa voz, en palabras por segundo. */
  palabrasPorSegundo: number;
  /**
   * Textos del formato serie que compone el código, no el modelo. Van en el idioma de salida:
   * un caption en inglés rematado con "Sígueme" delata que detrás hay una plantilla.
   */
  serie: {
    /** Recibe número de parte y total: "Parte 2/8". */
    parte: (n: number, total: number) => string;
    cta: string;
    ctaFinal: string;
  };
}

const CATALOGO: Record<string, Idioma> = {
  es: {
    codigo: "es",
    nombre: "español",
    voz: "es-MX-JorgeNeural",
    palabrasPorSegundo: 2.6,
    serie: {
      parte: (n, total) => `Parte ${n}/${total}`,
      cta: "Sígueme para no perderte la parte siguiente.",
      ctaFinal: "Serie completa en el perfil.",
    },
  },
  en: {
    codigo: "en",
    nombre: "inglés",
    voz: "en-US-AndrewNeural",
    palabrasPorSegundo: 2.9,
    serie: {
      parte: (n, total) => `Part ${n}/${total}`,
      cta: "Follow so you don't miss the next part.",
      ctaFinal: "Full series on my profile.",
    },
  },
  pt: {
    codigo: "pt",
    nombre: "portugués",
    voz: "pt-BR-AntonioNeural",
    palabrasPorSegundo: 2.6,
    serie: {
      parte: (n, total) => `Parte ${n}/${total}`,
      cta: "Me siga para não perder a próxima parte.",
      ctaFinal: "Série completa no perfil.",
    },
  },
  fr: {
    codigo: "fr",
    nombre: "francés",
    voz: "fr-FR-HenriNeural",
    palabrasPorSegundo: 2.7,
    serie: {
      parte: (n, total) => `Partie ${n}/${total}`,
      cta: "Abonne-toi pour ne pas rater la suite.",
      ctaFinal: "Série complète sur le profil.",
    },
  },
  it: {
    codigo: "it",
    nombre: "italiano",
    voz: "it-IT-DiegoNeural",
    palabrasPorSegundo: 2.7,
    serie: {
      parte: (n, total) => `Parte ${n}/${total}`,
      cta: "Seguimi per non perderti la prossima parte.",
      ctaFinal: "Serie completa sul profilo.",
    },
  },
  de: {
    codigo: "de",
    nombre: "alemán",
    voz: "de-DE-ConradNeural",
    palabrasPorSegundo: 2.4,
    serie: {
      parte: (n, total) => `Teil ${n}/${total}`,
      cta: "Folge mir, damit du den nächsten Teil nicht verpasst.",
      ctaFinal: "Komplette Serie im Profil.",
    },
  },
};

/** `en-US`, `EN`, `en_us` → `en`. Devuelve cadena vacía si no hay código. */
export function normalizarCodigo(codigo: string | undefined | null): string {
  return (codigo ?? "").trim().toLowerCase().split(/[-_]/)[0] ?? "";
}

/**
 * Resuelve un código a su entrada del catálogo. Un idioma desconocido no es un error:
 * Whisper reconoce muchos más de los que aquí se afinan, así que se cae a la voz
 * multilingüe con un ritmo conservador.
 */
export function resolverIdioma(codigo: string | undefined | null): Idioma {
  const base = normalizarCodigo(codigo);
  const conocido = CATALOGO[base];
  if (conocido) return conocido;
  return {
    codigo: base || "desconocido",
    nombre: base || "desconocido",
    voz: VOZ_FALLBACK,
    palabrasPorSegundo: 2.6,
    serie: CATALOGO.en!.serie,
  };
}

/** true si el idioma tiene voz y ritmo afinados en el catálogo. */
export function esIdiomaConocido(codigo: string | undefined | null): boolean {
  return normalizarCodigo(codigo) in CATALOGO;
}

export function idiomasSoportados(): string[] {
  return Object.keys(CATALOGO);
}
