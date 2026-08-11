"""Banco de pruebas de prompts: generar, medir y comparar dos versiones sobre el mismo material.

Refinar un prompt sin medir es adivinar. Este paquete existe para que un cambio de redacción
se pueda contrastar con el anterior sobre los mismos episodios, con las mismas cifras.

Ver `metricas` para qué se mide y por qué, y `__main__` para los comandos.
"""

from viralfarm.banco.metricas import Medida, comparar, medir, tabla

__all__ = ["Medida", "comparar", "medir", "tabla"]
