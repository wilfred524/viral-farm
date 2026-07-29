#!/usr/bin/env python
"""Transcribe un WAV con faster-whisper y emite JSON por stdout.

Contrato con el pipeline TS (ver src/lib/proceso.ts): stdout es JSON puro, todo log va a
stderr. Los timestamps por palabra son obligatorios: sin ellos no hay subtítulos karaoke.

Uso: python scripts/transcribir.py --audio audio.wav --modelo small --idioma es
"""

import argparse
import json
import sys


def log(mensaje: str) -> None:
    print(mensaje, file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcripción con faster-whisper")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--modelo", default="small")
    parser.add_argument("--idioma", default="es")
    # Por defecto CPU: con device="auto" ctranslate2 elige CUDA en cuanto ve una GPU NVIDIA y
    # revienta con "cublas64_12.dll is not found" si no están instaladas las libs de cuBLAS.
    parser.add_argument("--dispositivo", default="cpu", help="cpu | cuda")
    args = parser.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        log("Falta faster-whisper. Instálalo con: pip install faster-whisper")
        return 2

    dispositivo = args.dispositivo
    tipo_computo = "float16" if dispositivo == "cuda" else "int8"

    log(f"Cargando modelo {args.modelo} en {dispositivo} ({tipo_computo})...")
    modelo = WhisperModel(args.modelo, device=dispositivo, compute_type=tipo_computo)

    idioma = None if args.idioma in ("auto", "") else args.idioma
    segmentos_iter, info = modelo.transcribe(
        args.audio,
        language=idioma,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )

    segmentos = []
    for segmento in segmentos_iter:
        palabras = [
            {
                "texto": palabra.word.strip(),
                "inicio": round(palabra.start, 3),
                "fin": round(palabra.end, 3),
            }
            for palabra in (segmento.words or [])
            if palabra.word.strip()
        ]
        texto = segmento.text.strip()
        if not texto:
            continue
        segmentos.append(
            {
                "inicio": round(segmento.start, 3),
                "fin": round(segmento.end, 3),
                "texto": texto,
                "palabras": palabras,
            }
        )
        log(f"[{segmento.start:7.1f}s] {texto[:80]}")

    salida = {
        "idioma": info.language,
        "modelo": args.modelo,
        "duracion": round(info.duration, 3),
        "segmentos": segmentos,
    }
    json.dump(salida, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
