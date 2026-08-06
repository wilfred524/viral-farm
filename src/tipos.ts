/**
 * Contratos de los artefactos del pipeline.
 *
 * Cada paso lee y escribe archivos JSON bajo `media/<video_id>/`. Estos esquemas son la
 * fuente de verdad de ese contrato: validan tanto lo que produce un paso como lo que
 * consume el siguiente, de forma que un artefacto corrupto falla en el borde y no a mitad
 * de un render de varios minutos.
 */

import { z } from "zod";

/** Una palabra con su ventana temporal, en segundos relativos al medio que la contiene. */
export const PalabraSchema = z.object({
  texto: z.string(),
  inicio: z.number().nonnegative(),
  fin: z.number().nonnegative(),
});
export type Palabra = z.infer<typeof PalabraSchema>;

export const SegmentoSchema = z.object({
  inicio: z.number().nonnegative(),
  fin: z.number().nonnegative(),
  texto: z.string(),
  palabras: z.array(PalabraSchema),
});
export type Segmento = z.infer<typeof SegmentoSchema>;

// === fuente.json ===

export const FuenteSchema = z.object({
  videoId: z.string(),
  rutaOriginal: z.string(),
  duracion: z.number().positive(),
  ancho: z.number().int().positive(),
  alto: z.number().int().positive(),
  fps: z.number().positive(),
  /** Rotación declarada en metadata (los MOV de móvil suelen traer 90). */
  rotacion: z.number(),
  codecVideo: z.string(),
  codecAudio: z.string().nullable(),
  creadoEn: z.string(),
});
export type Fuente = z.infer<typeof FuenteSchema>;

// === transcripcion.json ===

export const TranscripcionSchema = z.object({
  idioma: z.string(),
  modelo: z.string(),
  duracion: z.number().nonnegative(),
  segmentos: z.array(SegmentoSchema),
});
export type Transcripcion = z.infer<typeof TranscripcionSchema>;

// === clips.json ===

/**
 * Anatomía del arco narrativo dentro de un episodio, en segundos relativos a su inicio.
 * Entre `desenlace` y el final del episodio va el cierre en tensión: lo que engancha con la
 * entrega siguiente.
 */
export const ArcoSchema = z.object({
  /** Pico de tensión. */
  cumbre: z.number().nonnegative(),
  /** Instante en que se cierra el arco que abrió el episodio. */
  desenlace: z.number().nonnegative(),
});
export type Arco = z.infer<typeof ArcoSchema>;

/** De qué dependió cada frontera del episodio: diagnóstico de la calidad del corte. */
export const AlineacionSchema = z.enum(["escena", "frase", "llm"]);
export type Alineacion = z.infer<typeof AlineacionSchema>;

export const ClipSchema = z.object({
  indice: z.number().int().nonnegative(),
  inicio: z.number().nonnegative(),
  fin: z.number().positive(),
  titulo: z.string(),
  razon: z.string(),
  puntuacion: z.number().min(0).max(10),

  // --- formato serie; ausentes en artefactos del formato "virales" ---
  /** Número de entrega, 1-based. Invariante del formato serie: `parte === indice + 1`. */
  parte: z.number().int().positive().optional(),
  totalPartes: z.number().int().positive().optional(),
  arco: ArcoSchema.optional(),
  /** Qué ocurre en el episodio; materia prima del recap de la entrega siguiente. */
  resumen: z.string().optional(),
  /** Tensión que queda abierta al final y que resuelve el episodio siguiente. */
  cliffhanger: z.string().optional(),
  /** Segundos del fuente saltados desde el fin del episodio anterior (0 = encadenados). */
  huecoAnterior: z.number().nonnegative().optional(),
  alineacion: z.object({ inicio: AlineacionSchema, fin: AlineacionSchema }).optional(),
});
export type Clip = z.infer<typeof ClipSchema>;

export const SerieSchema = z.object({
  titulo: z.string(),
  sinopsis: z.string(),
  totalPartes: z.number().int().positive(),
  /** Fracción del fuente cubierta por los episodios: control de calidad y de riesgo legal. */
  cobertura: z.number().min(0).max(1),
});
export type Serie = z.infer<typeof SerieSchema>;

export const ClipsSchema = z.object({
  modelo: z.string(),
  /** `virales` = comportamiento legado; ausente en artefactos anteriores al formato serie. */
  formato: z.enum(["virales", "serie"]).default("virales"),
  /** Solo en formato serie. */
  serie: SerieSchema.optional(),
  clips: z.array(ClipSchema),
});
export type Clips = z.infer<typeof ClipsSchema>;

// === clips/<n>/guion.json ===

/**
 * Un tramo cubre una porción del clip (tiempos relativos al inicio del clip).
 * - `original`: suena el audio ambiental a volumen pleno.
 * - `narracion`: entra la voz TTS y el audio ambiental se atenúa (ducking).
 * Los tramos de un guion cubren el clip completo, en orden y sin huecos ni solapes.
 */
export const TramoSchema = z.object({
  tipo: z.enum(["original", "narracion"]),
  inicio: z.number().nonnegative(),
  fin: z.number().positive(),
  /** Texto a narrar; obligatorio en tramos `narracion`, ausente en `original`. */
  texto: z.string().optional(),
});
export type Tramo = z.infer<typeof TramoSchema>;

export const GuionSchema = z.object({
  indice: z.number().int().nonnegative(),
  /**
   * Idioma en que están escritos hook, narración y caption (ISO 639-1). Puede no coincidir
   * con el del audio original; el paso de TTS elige la voz a partir de él.
   */
  idioma: z.string().default("es"),
  /** Frase corta que se superpone al principio del clip (gancho de 1.5 s). */
  hook: z.string(),
  tramos: z.array(TramoSchema).min(1),
  caption: z.string(),
  hashtags: z.array(z.string()),

  // --- formato serie ---
  parte: z.number().int().positive().optional(),
  totalPartes: z.number().int().positive().optional(),
  /** Texto del recap narrado que abre el episodio. Ausente en la parte 1. */
  recap: z.string().optional(),
  /**
   * Resumen de lo que se narró REALMENTE en este episodio, en el idioma de salida. Es la
   * entrada del recap del siguiente, y se prefiere al `resumen` planificado en clips.json.
   */
  resumen: z.string().optional(),
  /** Tensión abierta al final, tal como quedó narrada. */
  cliffhanger: z.string().optional(),
});
export type Guion = z.infer<typeof GuionSchema>;

// === clips/<n>/narracion.json ===

export const NarracionTramoSchema = z.object({
  /** Índice del tramo dentro de `guion.tramos`. */
  tramo: z.number().int().nonnegative(),
  archivo: z.string(),
  /** Segundo del clip en el que arranca el audio narrado. */
  desplazamiento: z.number().nonnegative(),
  duracion: z.number().positive(),
  /** Factor `atempo` aplicado para encajar el audio en el tramo (1 = sin ajuste). */
  tempo: z.number().positive(),
  palabras: z.array(PalabraSchema),
});
export type NarracionTramo = z.infer<typeof NarracionTramoSchema>;

export const NarracionSchema = z.object({
  voz: z.string(),
  tramos: z.array(NarracionTramoSchema),
});
export type Narracion = z.infer<typeof NarracionSchema>;

// === props que recibe la composición de Remotion ===

export const SubtituloSchema = z.object({
  texto: z.string(),
  inicio: z.number().nonnegative(),
  fin: z.number().nonnegative(),
  /** De dónde salió la palabra: define el estilo del subtítulo. */
  origen: z.enum(["original", "narracion"]),
});
export type Subtitulo = z.infer<typeof SubtituloSchema>;

export const PropsClipSchema = z.object({
  /** Ruta del base.mp4 relativa al publicDir de Remotion. */
  video: z.string(),
  duracion: z.number().positive(),
  fps: z.number().positive(),
  hook: z.string(),
  subtitulos: z.array(SubtituloSchema),
  /** Formato serie: la composición pinta una chapa "PARTE n / N" sobre el hook. */
  parte: z.number().int().positive().optional(),
  totalPartes: z.number().int().positive().optional(),
});
export type PropsClip = z.infer<typeof PropsClipSchema>;
