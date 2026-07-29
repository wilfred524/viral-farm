#!/usr/bin/env python
"""Sintetiza narración con Edge-TTS y emite los timings por palabra en JSON por stdout.

Los eventos WordBoundary de Edge-TTS dan el instante de cada palabra dentro del audio
generado, que es lo que permite sincronizar los subtítulos karaoke de la narración.

Contrato con el pipeline TS: stdout es JSON puro, los logs van a stderr.

Uso: python scripts/tts.py --texto "..." --voz es-MX-JorgeNeural --salida narracion/0.mp3
"""

import argparse
import asyncio
import json
import sys


def log(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


async def sintetizar(texto: str, voz: str, salida: str, ritmo: str) -> dict:
    import edge_tts

    # boundary="WordBoundary" es obligatorio en edge-tts 7.x: por defecto solo emite
    # SentenceBoundary, que no basta para sincronizar subtítulos palabra a palabra.
    comunicador = edge_tts.Communicate(texto, voz, rate=ritmo, boundary="WordBoundary")
    palabras = []
    with open(salida, "wb") as archivo:
        async for fragmento in comunicador.stream():
            if fragmento["type"] == "audio":
                archivo.write(fragmento["data"])
            elif fragmento["type"] == "WordBoundary":
                # Edge-TTS trabaja en unidades de 100 ns.
                inicio = fragmento["offset"] / 10_000_000
                duracion = fragmento["duration"] / 10_000_000
                palabras.append(
                    {
                        "texto": fragmento["text"],
                        "inicio": round(inicio, 3),
                        "fin": round(inicio + duracion, 3),
                    }
                )

    return {"voz": voz, "archivo": salida, "palabras": palabras}


def main() -> int:
    parser = argparse.ArgumentParser(description="Síntesis de voz con Edge-TTS")
    parser.add_argument("--texto", required=True)
    parser.add_argument("--voz", default="es-MX-JorgeNeural")
    parser.add_argument("--salida", required=True)
    parser.add_argument("--ritmo", default="+0%", help="Ajuste de velocidad, p. ej. +10%%")
    args = parser.parse_args()

    if not args.texto.strip():
        log("El texto a narrar está vacío.")
        return 2

    try:
        import edge_tts  # noqa: F401
    except ImportError:
        log("Falta edge-tts. Instálalo con: pip install edge-tts")
        return 2

    log(f"Sintetizando con {args.voz}: {args.texto[:70]}…")
    resultado = asyncio.run(sintetizar(args.texto, args.voz, args.salida, args.ritmo))

    if not resultado["palabras"]:
        log("Aviso: el servicio no devolvió timings por palabra.")

    json.dump(resultado, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
