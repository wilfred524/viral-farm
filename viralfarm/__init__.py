"""ViralFarm — decide qué contenido producir y lo produce.

Arquitectura en `docs/arquitectura.md`. Las capas, de dentro afuera:

- `contratos/`   esquemas Pydantic de los artefactos; la interfaz entre pasos.
- `dominio/`     lógica pura: sin disco, sin red, sin configuración. Es lo que se testea.
- `adaptadores/` todo lo que habla con el exterior (ffmpeg, whisper, LLM, TTS).
- `pasos/`       orquestación fina: leer artefacto → dominio → escribir artefacto.
- `radar/`       subsistema que decide qué producir.
"""

__version__ = "0.2.0"
