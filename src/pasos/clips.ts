/**
 * Paso 3 — Selección de clips. El LLM lee la transcripción con timestamps y elige los
 * fragmentos con más potencial de retención (Módulo 02 de la propuesta técnica).
 *
 * La salida del modelo se valida y además se corrige aquí: se ajusta a fronteras de frase,
 * se recortan solapes y se descartan rangos imposibles. El LLM propone, el código verifica.
 */

import { z } from "zod";
import { config } from "../config.js";
import { ClipsSchema, FuenteSchema, TranscripcionSchema, type Clip, type Clips, type Transcripcion } from "../tipos.js";
import { pedirEstructurado } from "../lib/llm.js";
import { escribirJson, leerJson, pasoIdempotente, rutas } from "../lib/artefactos.js";

const DURACION_MIN = 20;
const DURACION_MAX = 60;

const RespuestaSchema = z.object({
  clips: z.array(
    z.object({
      inicio: z.number().describe("Segundo de inicio del clip en el video fuente"),
      fin: z.number().describe("Segundo de fin del clip en el video fuente"),
      titulo: z.string().describe("Título corto y con gancho para el clip"),
      razon: z.string().describe("Por qué este fragmento retiene la atención"),
      puntuacion: z.number().describe("Potencial viral de 0 a 10"),
    }),
  ),
});

const SISTEMA = `Eres un editor de contenido vertical (TikTok, Reels, Shorts) especializado en
detectar los momentos de un video largo con más potencial de retención.

Buscas fragmentos que:
- Abren con un gancho en los primeros 1.5 segundos (pregunta, afirmación fuerte, tensión).
- Se entienden solos, sin haber visto el resto del video.
- Tienen un arco: tensión y resolución o giro final.
- Empiezan y terminan en frontera de frase, nunca a mitad de palabra.

Evitas: introducciones, agradecimientos, transiciones administrativas y tramos sin habla.`;

/** Representación compacta de la transcripción para el prompt. */
function formatearTranscripcion(transcripcion: Transcripcion): string {
  return transcripcion.segmentos
    .map((s) => `[${s.inicio.toFixed(1)}–${s.fin.toFixed(1)}] ${s.texto}`)
    .join("\n");
}

/** Lleva un instante al comienzo/fin de segmento más cercano para no cortar frases. */
function ajustarAFrontera(
  tiempo: number,
  transcripcion: Transcripcion,
  extremo: "inicio" | "fin",
): number {
  const candidatos = transcripcion.segmentos.map((s) => (extremo === "inicio" ? s.inicio : s.fin));
  let mejor = tiempo;
  let distancia = Infinity;
  for (const candidato of candidatos) {
    const d = Math.abs(candidato - tiempo);
    if (d < distancia && d <= 2) {
      distancia = d;
      mejor = candidato;
    }
  }
  return mejor;
}

function normalizar(
  propuestos: z.infer<typeof RespuestaSchema>["clips"],
  transcripcion: Transcripcion,
  duracionFuente: number,
): Clip[] {
  const validos = propuestos
    .map((c) => ({
      ...c,
      inicio: Math.max(0, ajustarAFrontera(c.inicio, transcripcion, "inicio")),
      fin: Math.min(duracionFuente, ajustarAFrontera(c.fin, transcripcion, "fin")),
    }))
    .filter((c) => {
      const duracion = c.fin - c.inicio;
      return duracion >= DURACION_MIN * 0.75 && duracion <= DURACION_MAX * 1.5;
    })
    .sort((a, b) => a.inicio - b.inicio);

  // Elimina solapes conservando el clip mejor puntuado de cada colisión.
  const sinSolapes: typeof validos = [];
  for (const clip of validos) {
    const previo = sinSolapes[sinSolapes.length - 1];
    if (previo && clip.inicio < previo.fin) {
      if (clip.puntuacion > previo.puntuacion) sinSolapes[sinSolapes.length - 1] = clip;
      continue;
    }
    sinSolapes.push(clip);
  }

  return sinSolapes.map((c, indice) => ({
    indice,
    inicio: c.inicio,
    fin: c.fin,
    titulo: c.titulo,
    razon: c.razon,
    puntuacion: Math.min(10, Math.max(0, c.puntuacion)),
  }));
}

export async function seleccionarClips(videoId: string, n = 5, force = false): Promise<Clips> {
  const fuente = await leerJson(rutas.fuente(videoId), FuenteSchema);
  const transcripcion = await leerJson(rutas.transcripcion(videoId), TranscripcionSchema);

  return pasoIdempotente({
    salida: rutas.clips(videoId),
    force,
    nombre: "selección de clips",
    leer: () => leerJson(rutas.clips(videoId), ClipsSchema),
    calcular: async () => {
      const prompt = `Video de ${fuente.duracion.toFixed(0)} segundos. Transcripción con timestamps:

${formatearTranscripcion(transcripcion)}

Selecciona los ${n} fragmentos con más potencial viral. Cada uno debe durar entre
${DURACION_MIN} y ${DURACION_MAX} segundos, no solaparse con los demás y empezar y terminar
en frontera de frase (usa los timestamps de arriba). Ordénalos por potencial descendente.`;

      const respuesta = await pedirEstructurado(RespuestaSchema, {
        sistema: SISTEMA,
        prompt,
        etiqueta: "clips",
      });

      const clips = normalizar(respuesta.clips, transcripcion, fuente.duracion).slice(0, n);
      if (clips.length === 0) {
        throw new Error(
          "Ningún clip propuesto superó la validación (duración o solapes). Revisa la transcripción.",
        );
      }
      if (clips.length < n) {
        console.warn(`· clips: se pedían ${n} pero solo ${clips.length} superaron la validación.`);
      }

      const resultado = await escribirJson(rutas.clips(videoId), ClipsSchema, {
        modelo: config.modeloLlm,
        clips,
      });
      for (const clip of resultado.clips) {
        console.log(
          `  #${clip.indice} ${clip.inicio.toFixed(1)}–${clip.fin.toFixed(1)}s ` +
            `(${(clip.fin - clip.inicio).toFixed(0)}s, ${clip.puntuacion}/10) — ${clip.titulo}`,
        );
      }
      return resultado;
    },
  });
}
