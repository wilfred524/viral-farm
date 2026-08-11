"""Único punto del proyecto donde se lanzan subprocesos (ffmpeg, ffprobe, python).

Centralizarlo hace que todos los errores externos lleguen con el mismo formato: comando,
código de salida y las últimas líneas de stderr, que es lo que de verdad explica por qué
falló ffmpeg. Sin esto, cada llamada inventa su propio manejo y un fallo se lee como un
`CalledProcessError` sin contexto.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: Últimas líneas de stderr que se incluyen en el error. ffmpeg escupe cientos de líneas
#: de progreso; la causa real está casi siempre al final.
LINEAS_ERROR = 12


class ErrorProceso(RuntimeError):
    """Un proceso externo terminó con código distinto de cero."""

    def __init__(self, comando: str, codigo: int | None, stderr: str) -> None:
        self.comando = comando
        self.codigo = codigo
        self.stderr = stderr
        cola = "\n".join(stderr.strip().splitlines()[-LINEAS_ERROR:])
        super().__init__(f'El comando "{comando}" terminó con código {codigo}.\n{cola}')


@dataclass
class ResultadoProceso:
    stdout: str
    stderr: str


def ejecutar(
    comando: str,
    args: list[str],
    etiqueta: str | None = None,
    cwd: str | None = None,
    on_stderr: Callable[[str], None] | None = None,
) -> ResultadoProceso:
    """Lanza un proceso y devuelve su salida.

    `on_stderr` recibe cada línea conforme llega: ffmpeg publica su progreso ahí, y en un
    montaje de varios minutos un proceso mudo es indistinguible de uno colgado.
    """
    etiqueta = etiqueta or comando.replace("\\", "/").rsplit("/", 1)[-1]

    if on_stderr is None:
        completado = subprocess.run(
            [comando, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
        if completado.returncode != 0:
            raise ErrorProceso(etiqueta, completado.returncode, completado.stderr or "")
        return ResultadoProceso(completado.stdout or "", completado.stderr or "")

    proceso = subprocess.Popen(
        [comando, *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    lineas: list[str] = []
    assert proceso.stderr is not None
    for linea in proceso.stderr:
        lineas.append(linea)
        on_stderr(linea.rstrip())
    salida = proceso.stdout.read() if proceso.stdout else ""
    proceso.wait()

    stderr = "".join(lineas)
    if proceso.returncode != 0:
        raise ErrorProceso(etiqueta, proceso.returncode, stderr)
    return ResultadoProceso(salida, stderr)


def ejecutar_json(
    comando: str, args: list[str], etiqueta: str | None = None
) -> dict[str, Any]:
    """Ejecuta un proceso cuyo stdout es JSON puro.

    Es el contrato de ffprobe y de los scripts auxiliares: los logs van a stderr, los
    datos a stdout. Si se mezclan, esto lo detecta aquí en vez de dos pasos después.
    """
    resultado = ejecutar(comando, args, etiqueta)
    try:
        datos: dict[str, Any] = json.loads(resultado.stdout)
        return datos
    except json.JSONDecodeError as error:
        muestra = resultado.stdout[:400]
        raise ErrorProceso(
            etiqueta or comando,
            0,
            f"La salida no es JSON válido ({error}). Primeros caracteres:\n{muestra}",
        ) from error
