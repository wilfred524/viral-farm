"""Contratos de los artefactos del pipeline.

Cada paso lee y escribe archivos JSON bajo `workspace/trabajo/<video_id>/`. Estos esquemas son
la fuente de verdad de ese contrato: validan tanto lo que produce un paso como lo que consume
el siguiente, de forma que un artefacto corrupto falla en el borde y no a mitad de un render de
varios minutos.

Los mismos esquemas validan las respuestas del LLM, así que un fallo de formato del modelo se
detecta en el mismo sitio que un artefacto corrupto.
"""

from viralfarm.contratos.comunes import Palabra, Segmento
from viralfarm.contratos.fuente import Fuente
from viralfarm.contratos.guion import Guion, TipoTramo, Tramo
from viralfarm.contratos.senales import CorteVisual, Senales, VentanaAudio
from viralfarm.contratos.serie import (
    Alineacion,
    Arco,
    Candidato,
    Candidatos,
    Episodio,
    ScoreEpisodio,
    Serie,
)
from viralfarm.contratos.subtitulos import OrigenSubtitulo, Subtitulo
from viralfarm.contratos.timeline import EventoTimeline, Timeline, TipoEvento
from viralfarm.contratos.transcripcion import Transcripcion
from viralfarm.contratos.vision import Observacion, Vision
from viralfarm.contratos.voz import Voz, VozTramo

__all__ = [
    "Alineacion",
    "Arco",
    "Candidato",
    "Candidatos",
    "CorteVisual",
    "Episodio",
    "EventoTimeline",
    "Fuente",
    "Guion",
    "Observacion",
    "OrigenSubtitulo",
    "Palabra",
    "ScoreEpisodio",
    "Segmento",
    "Senales",
    "Serie",
    "Subtitulo",
    "Timeline",
    "TipoEvento",
    "TipoTramo",
    "Tramo",
    "Transcripcion",
    "VentanaAudio",
    "Vision",
    "Voz",
    "VozTramo",
]
