"""Atenuación del audio ambiental bajo la narración.

El episodio **conserva su duración**: donde entra la voz, el material no se corta, se atenúa.
La expresión resultante la consume el filtro `volume=...:eval=frame` de ffmpeg.
"""

from __future__ import annotations

from collections.abc import Sequence

#: Duración de la rampa de entrada y salida de la atenuación, en segundos. Sin rampa, el
#: cambio de volumen se oye como un salto brusco.
RAMPA = 0.25


def db_a_factor(db: float) -> float:
    """Convierte dB a factor lineal de amplitud."""
    return float(10 ** (db / 20))


def expresion_ducking(
    tramos: Sequence[tuple[float, float]],
    factor: float,
    rampa: float = RAMPA,
) -> str:
    """Volumen del audio ambiental a lo largo del episodio, como expresión de ffmpeg.

    Vale 1 fuera de los tramos narrados y `factor` dentro, con rampas en cada frontera. Cada
    tramo aporta un trapecio entre 0 y 1 y se toma el mayor de todos, de modo que tramos
    solapados o pegados no se suman ni dejan huecos.

    `tramos` son pares `(inicio, fin)` en segundos relativos al episodio.
    """
    if not tramos:
        return "1"
    if rampa <= 0:
        raise ValueError("la rampa debe ser positiva")

    trapecios = [
        f"min(1,max(0,min((t-{max(inicio - rampa, 0.0):.3f})/{rampa},"
        f"({fin + rampa:.3f}-t)/{rampa})))"
        for inicio, fin in tramos
    ]

    combinado = trapecios[0]
    for trapecio in trapecios[1:]:
        combinado = f"max({combinado},{trapecio})"

    return f"1-{1 - factor:.4f}*({combinado})"
