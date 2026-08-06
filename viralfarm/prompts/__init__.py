"""Prompts del sistema y esquemas de respuesta del LLM.

Viven fuera de los pasos y del dominio: son el texto que más se toca y la parte que más se
itera, así que conviene poder leerlos y editarlos sin navegar lógica alrededor.

Los esquemas de respuesta que hay aquí son el contrato con el **modelo**, distinto del
contrato con el **artefacto** (`viralfarm/contratos/`). El modelo propone en su formato; el
dominio normaliza, repara y produce el artefacto.
"""
