/**
 * Cliente del LLM (Anthropic) con salida estructurada.
 *
 * Los pasos `clips` y `guion` necesitan JSON que cumpla un esquema exacto: se usa
 * `messages.parse()` con `zodOutputFormat`, que restringe la respuesta al esquema y la
 * valida antes de devolverla. Así un fallo de formato se detecta aquí y no dos pasos después.
 */

import path from "node:path";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import type { z } from "zod";
import { config, requiereClaveAnthropic } from "../config.js";

let cliente: Anthropic | undefined;

function obtenerCliente(): Anthropic {
  if (!cliente) {
    cliente = new Anthropic({ apiKey: requiereClaveAnthropic() });
  }
  return cliente;
}

export interface OpcionesLlm {
  sistema: string;
  prompt: string;
  /** Etiqueta para los logs de coste. */
  etiqueta: string;
  maxTokens?: number;
  /** low | medium | high | xhigh | max. */
  esfuerzo?: "low" | "medium" | "high" | "xhigh" | "max";
}

/** Acumulado de tokens de la ejecución, para comparar con la matriz de costos de docs/decisiones.md. */
export const uso = { entrada: 0, salida: 0 };

/** `guion #3` → `guion-3`: la etiqueta se usa como nombre de archivo. */
function nombreArchivo(etiqueta: string): string {
  return etiqueta.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

/**
 * Respuesta guardada en disco para esa etiqueta, o null si no hay ninguna.
 *
 * Con `LLM_RESPUESTAS_DIR` definido el pipeline funciona sin clave de API: las respuestas se
 * escriben a mano (o se reutilizan de una ejecución anterior) y aun así pasan por la misma
 * validación Zod que las reales, que es donde se rompen las cosas de verdad.
 */
async function respuestaEnDisco(etiqueta: string): Promise<unknown | null> {
  if (!config.llmRespuestasDir) return null;
  const ruta = path.join(config.llmRespuestasDir, `${nombreArchivo(etiqueta)}.json`);
  try {
    return JSON.parse(await readFile(ruta, "utf8"));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new Error(`No se pudo leer la respuesta guardada ${ruta}: ${String(error)}`);
  }
}

async function guardarRespuesta(etiqueta: string, datos: unknown): Promise<void> {
  if (!config.llmRespuestasDir) return;
  await mkdir(config.llmRespuestasDir, { recursive: true });
  const ruta = path.join(config.llmRespuestasDir, `${nombreArchivo(etiqueta)}.json`);
  await writeFile(ruta, JSON.stringify(datos, null, 2), "utf8");
}

export async function pedirEstructurado<T extends z.ZodTypeAny>(
  esquema: T,
  opciones: OpcionesLlm,
): Promise<z.infer<T>> {
  const guardada = await respuestaEnDisco(opciones.etiqueta);
  if (guardada !== null) {
    const validada = esquema.safeParse(guardada);
    if (!validada.success) {
      throw new Error(
        `La respuesta guardada de "${opciones.etiqueta}" no cumple el esquema:\n` +
          validada.error.issues.map((i) => `  · ${i.path.join(".")}: ${i.message}`).join("\n"),
      );
    }
    console.log(`· ${opciones.etiqueta}: respuesta leída de disco (sin llamada a la API)`);
    return validada.data as z.infer<T>;
  }

  const respuesta = await obtenerCliente().messages.parse({
    model: config.modeloLlm,
    max_tokens: opciones.maxTokens ?? 16000,
    system: opciones.sistema,
    output_config: {
      format: zodOutputFormat(esquema),
      ...(opciones.esfuerzo ? { effort: opciones.esfuerzo } : {}),
    },
    messages: [{ role: "user", content: opciones.prompt }],
  });

  if (respuesta.stop_reason === "refusal") {
    throw new Error(
      `El modelo rechazó la petición en el paso "${opciones.etiqueta}"` +
        (respuesta.stop_details?.explanation ? `: ${respuesta.stop_details.explanation}` : "."),
    );
  }
  if (respuesta.stop_reason === "max_tokens") {
    throw new Error(
      `La respuesta de "${opciones.etiqueta}" se truncó por max_tokens. Sube maxTokens o reduce la entrada.`,
    );
  }

  uso.entrada += respuesta.usage.input_tokens;
  uso.salida += respuesta.usage.output_tokens;
  console.log(
    `· ${opciones.etiqueta}: ${respuesta.usage.input_tokens} tokens entrada / ` +
      `${respuesta.usage.output_tokens} salida (${config.modeloLlm})`,
  );

  const datos = respuesta.parsed_output;
  if (datos === null || datos === undefined) {
    throw new Error(`El modelo no devolvió una respuesta válida en el paso "${opciones.etiqueta}".`);
  }
  // Doble uso del directorio: caché de lo ya pagado, además de banco de pruebas offline.
  await guardarRespuesta(opciones.etiqueta, datos);
  return datos as z.infer<T>;
}
