"""Carga de las plantillas de prompt desde `plantillas/*.md`.

Los prompts salieron del código por una razón práctica: es el texto que más se itera y el
que menos tiene que ver con programar. Quien refina cómo se cuenta una historia edita
markdown; nadie abre un `.py` para cambiar una frase.

Dos garantías a cambio de esa comodidad:

- **Los marcadores se validan al cargar.** Un `{cumbre}` mal escrito falla al arrancar, con
  el nombre del marcador y la lista de los válidos, en vez de colarse como texto literal en
  el prompt y producir un guion raro que nadie sabe explicar.
- **Cada plantilla tiene una versión.** Es el hash de su contenido, y viaja al artefacto.
  Sin eso no se puede atribuir una mejora a un cambio de prompt, que es exactamente lo que
  necesita un proceso de refinamiento.
"""

from __future__ import annotations

import hashlib
import re
from functools import cache
from pathlib import Path
from string import Formatter

DIR_PLANTILLAS = Path(__file__).resolve().parent / "plantillas"

#: Longitud del hash que identifica una versión de plantilla. Ocho caracteres bastan para
#: distinguir iteraciones de un mismo archivo y caben en un log sin estorbar.
LONGITUD_VERSION = 8


class PlantillaInvalida(ValueError):
    """La plantilla no existe o usa un marcador que el código no sabe rellenar."""


def _marcadores(texto: str) -> set[str]:
    """Nombres entre llaves que `str.format` intentaría sustituir."""
    return {campo for _, campo, _, _ in Formatter().parse(texto) if campo}


@cache
def _leer(nombre: str) -> str:
    ruta = DIR_PLANTILLAS / f"{nombre}.md"
    if not ruta.is_file():
        disponibles = sorted(p.stem for p in DIR_PLANTILLAS.glob("*.md") if p.stem != "README")
        raise PlantillaInvalida(
            f"No existe la plantilla {ruta.name}. Disponibles: {', '.join(disponibles)}"
        )
    texto = ruta.read_text(encoding="utf-8")
    # La cabecera de documentación va entre <!-- --> y no se le manda al modelo: sirve para
    # que quien edite el archivo sepa qué marcadores tiene a mano.
    return re.sub(r"<!--.*?-->\s*", "", texto, flags=re.S).strip()


def version(nombre: str) -> str:
    """Identificador del contenido actual de la plantilla.

    Se guarda junto al artefacto que produjo. Dos guiones con la misma versión de prompt son
    comparables; con versiones distintas, la diferencia puede venir del prompt y no del
    modelo.
    """
    return hashlib.sha256(_leer(nombre).encode("utf-8")).hexdigest()[:LONGITUD_VERSION]


def render(nombre: str, **valores: object) -> str:
    """Plantilla con sus marcadores sustituidos.

    Falla si la plantilla pide algo que no se le pasa, o si se le pasa algo que no usa: lo
    primero produciría un prompt roto, lo segundo suele significar que alguien renombró un
    marcador y se olvidó de un sitio.
    """
    texto = _leer(nombre)
    pedidos = _marcadores(texto)
    dados = set(valores)

    if faltan := pedidos - dados:
        raise PlantillaInvalida(
            f"{nombre}.md usa marcadores que nadie rellena: {', '.join(sorted(faltan))}. "
            f"Disponibles: {', '.join(sorted(dados)) or '(ninguno)'}"
        )
    if sobran := dados - pedidos:
        raise PlantillaInvalida(
            f"A {nombre}.md se le pasan valores que no usa: {', '.join(sorted(sobran))}. "
            "¿Se renombró un marcador en el markdown?"
        )

    return texto.format(**valores)


def recargar() -> None:
    """Olvida las plantillas cacheadas. Para editar el markdown sin reiniciar el proceso."""
    _leer.cache_clear()
