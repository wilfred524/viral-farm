"""Cliente de LLM con salida estructurada, independiente del proveedor.

Los pasos que piden JSON al modelo (serie, guion, visión) necesitan una respuesta que cumpla
un esquema exacto. La estrategia depende de lo que ofrezca el proveedor:

- **Anthropic** tiene *structured outputs* nativos: la respuesta se restringe al esquema en el
  servidor y llega ya validada.
- **DeepSeek** habla el protocolo de OpenAI y ofrece *JSON mode*: garantiza JSON sintáctico,
  **no** que cumpla tu esquema. La garantía la pone aquí el código: se valida con Pydantic y,
  si falla, se reintenta devolviéndole al modelo los errores concretos de validación.

Esa diferencia es la razón de que el cliente sea una interfaz y no una función: el paso pide
"dame esto validado" y no sabe cuál de las dos mecánicas hubo detrás.

El caché va **indexado por `video_id`** — el fallo nº1 de la Fase 1 era una caché global por
etiqueta, que servía el guion de una película cuando se procesaba la siguiente.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

#: Reintentos cuando la respuesta no valida contra el esquema.
REINTENTOS = 2
#: Los prompts de este proyecto son pequeños (una serie completa ronda los 3.000 tokens de
#: salida). El tope es holgado a propósito, no una estimación ajustada.
MAX_TOKENS_DEFECTO = 8000
TIMEOUT_SEG = 300.0


class ErrorLlm(RuntimeError):
    """El modelo no devolvió algo utilizable, ni siquiera tras reintentar."""


@dataclass
class Uso:
    """Acumulado de tokens de la ejecución, para contrastar con la matriz de costos."""

    entrada: int = 0
    salida: int = 0
    llamadas: int = 0

    def sumar(self, entrada: int, salida: int) -> None:
        self.entrada += entrada
        self.salida += salida
        self.llamadas += 1


class ClienteLlm(Protocol):
    """Lo que un paso necesita de un LLM. Nada más."""

    modelo: str
    uso: Uso

    def pedir_estructurado(
        self,
        esquema: type[T],
        sistema: str,
        prompt: str,
        etiqueta: str,
        max_tokens: int = MAX_TOKENS_DEFECTO,
    ) -> T: ...


# ---------------------------------------------------------------------------
# DeepSeek (protocolo compatible con OpenAI)
# ---------------------------------------------------------------------------


def _esquema_para_prompt(esquema: type[BaseModel]) -> str:
    """Esquema JSON legible para incrustar en el prompt.

    DeepSeek no acepta un esquema como parámetro: su JSON mode solo garantiza que la salida
    sea JSON válido. Para que además cumpla la forma que queremos, el esquema tiene que ir
    dentro del prompt.
    """
    return json.dumps(esquema.model_json_schema(), ensure_ascii=False, indent=2)


def _extraer_json(texto: str) -> str:
    """Aísla el objeto JSON de una respuesta que puede venir envuelta en markdown."""
    limpio = texto.strip()
    cerca = re.search(r"```(?:json)?\s*(.*?)```", limpio, re.S)
    if cerca:
        limpio = cerca.group(1).strip()
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio != -1 and fin > inicio:
        return limpio[inicio : fin + 1]
    return limpio


def _errores_legibles(error: ValidationError) -> str:
    return "\n".join(
        f"  · {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()
    )


@dataclass
class ClienteDeepSeek:
    """DeepSeek vía su API compatible con OpenAI.

    Mucho más barato que Claude por token, lo que importa aquí porque el formato serie hace
    una llamada por episodio. A cambio no hay garantía de esquema: la pone el bucle de
    reintento de `pedir_estructurado`.
    """

    api_key: str
    modelo: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    uso: Uso = field(default_factory=Uso)

    def _completar(self, sistema: str, mensajes: list[dict[str, str]], max_tokens: int) -> str:
        respuesta = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.modelo,
                "messages": [{"role": "system", "content": sistema}, *mensajes],
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
            timeout=TIMEOUT_SEG,
        )
        if respuesta.status_code != 200:
            raise ErrorLlm(
                f"DeepSeek respondió {respuesta.status_code}: {respuesta.text[:400]}"
            )

        datos = respuesta.json()
        uso = datos.get("usage") or {}
        self.uso.sumar(uso.get("prompt_tokens", 0), uso.get("completion_tokens", 0))

        opciones = datos.get("choices") or []
        if not opciones:
            raise ErrorLlm("DeepSeek no devolvió ninguna opción de respuesta.")

        opcion = opciones[0]
        if opcion.get("finish_reason") == "length":
            raise ErrorLlm(
                f"La respuesta se truncó por max_tokens ({max_tokens}). "
                "Sube el tope o reduce lo que se pide en una sola llamada."
            )
        return opcion["message"]["content"] or ""

    def pedir_estructurado(
        self,
        esquema: type[T],
        sistema: str,
        prompt: str,
        etiqueta: str,
        max_tokens: int = MAX_TOKENS_DEFECTO,
    ) -> T:
        """Pide JSON que cumpla `esquema`, reintentando con los errores de validación.

        Devolverle al modelo el error concreto ("episodios.3.fin: debe ser mayor que inicio")
        es mucho más eficaz que repetir el prompt entero: casi siempre acierta al segundo
        intento.
        """
        sistema_json = (
            f"{sistema}\n\n"
            "Responde ÚNICAMENTE con un objeto JSON válido que cumpla este esquema, "
            "sin texto alrededor y sin bloques de markdown:\n\n"
            f"{_esquema_para_prompt(esquema)}"
        )
        mensajes: list[dict[str, str]] = [{"role": "user", "content": prompt}]
        ultimo: ValidationError | None = None

        for intento in range(REINTENTOS + 1):
            crudo = self._completar(sistema_json, mensajes, max_tokens)
            try:
                return esquema.model_validate_json(_extraer_json(crudo))
            except ValidationError as error:
                ultimo = error
                if intento == REINTENTOS:
                    break
                mensajes += [
                    {"role": "assistant", "content": crudo},
                    {
                        "role": "user",
                        "content": (
                            "Esa respuesta no cumple el esquema:\n"
                            f"{_errores_legibles(error)}\n\n"
                            "Devuelve el JSON corregido, completo y sin texto alrededor."
                        ),
                    },
                ]
            except json.JSONDecodeError as error:
                raise ErrorLlm(
                    f'La respuesta de "{etiqueta}" no es JSON válido: {error}'
                ) from error

        raise ErrorLlm(
            f'La respuesta de "{etiqueta}" no cumplió el esquema tras {REINTENTOS + 1} '
            f"intentos:\n{_errores_legibles(ultimo) if ultimo else ''}"
        )


# ---------------------------------------------------------------------------
# Caché en disco, indexada por video
# ---------------------------------------------------------------------------


def _nombre_archivo(etiqueta: str) -> str:
    """`guion parte 3` → `guion-parte-3`."""
    return re.sub(r"[^a-z0-9]+", "-", etiqueta.strip().lower()).strip("-")


@dataclass
class CacheLlm:
    """Respuestas del LLM en disco, **separadas por vídeo**.

    Doble uso: caché de lo ya pagado, y banco de pruebas para ejercitar el pipeline sin clave
    de API — las respuestas se pueden escribir a mano y pasan por la misma validación.
    """

    dir_base: Path
    video_id: str

    def _ruta(self, etiqueta: str) -> Path:
        return self.dir_base / self.video_id / f"{_nombre_archivo(etiqueta)}.json"

    def leer(self, esquema: type[T], etiqueta: str) -> T | None:
        ruta = self._ruta(etiqueta)
        if not ruta.exists():
            return None
        try:
            return esquema.model_validate_json(ruta.read_text(encoding="utf-8"))
        except ValidationError as error:
            raise ErrorLlm(
                f"La respuesta cacheada {ruta} ya no cumple el esquema:\n"
                f"{_errores_legibles(error)}\n"
                "Bórrala para volver a pedirla."
            ) from error

    def escribir(self, etiqueta: str, datos: BaseModel) -> Path:
        ruta = self._ruta(etiqueta)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            datos.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )
        return ruta


def pedir_con_cache(
    cliente: ClienteLlm,
    cache: CacheLlm | None,
    esquema: type[T],
    sistema: str,
    prompt: str,
    etiqueta: str,
    max_tokens: int = MAX_TOKENS_DEFECTO,
    force: bool = False,
) -> tuple[T, bool]:
    """Devuelve `(resultado, vino_de_cache)`. La misma política de idempotencia de los pasos."""
    if cache is not None and not force:
        guardado = cache.leer(esquema, etiqueta)
        if guardado is not None:
            return guardado, True

    resultado = cliente.pedir_estructurado(esquema, sistema, prompt, etiqueta, max_tokens)
    if cache is not None:
        cache.escribir(etiqueta, resultado)
    return resultado, False


def cargar_cliente(config: Any | None = None) -> ClienteLlm:
    """Construye el cliente del proveedor configurado. Falla con un mensaje accionable."""
    import os

    proveedor = os.environ.get("LLM_PROVEEDOR", "deepseek").strip().lower()
    if proveedor == "deepseek":
        clave = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not clave:
            raise ErrorLlm("Falta DEEPSEEK_API_KEY en el entorno o en .env.")
        modelo = os.environ.get("LLM_MODELO", "deepseek-chat").strip()
        return ClienteDeepSeek(api_key=clave, modelo=modelo)
    raise ErrorLlm(
        f"Proveedor de LLM no soportado: {proveedor!r}. Soportados: deepseek. "
        "(Anthropic llega con el resto de la fase 2.)"
    )
