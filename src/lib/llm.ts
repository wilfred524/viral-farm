/**
 * Cliente del LLM (Anthropic) con salida estructurada.
 *
 * Los pasos `clips` y `guion` necesitan JSON que cumpla un esquema exacto: se usa
 * `messages.parse()` con `zodOutputFormat`, que restringe la respuesta al esquema y la
 * valida antes de devolverla. Así un fallo de formato se detecta aquí y no dos pasos después.
 */

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

export async function pedirEstructurado<T extends z.ZodTypeAny>(
  esquema: T,
  opciones: OpcionesLlm,
): Promise<z.infer<T>> {
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
  return datos as z.infer<T>;
}
