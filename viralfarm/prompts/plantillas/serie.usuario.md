<!--
Marcadores: duracion, minutos, idioma_origen, timeline, max_episodios, idioma_salida,
            duracion_min, duracion_max, duracion_objetivo, cobertura_max, cola_minima
Los numericos salen de dominio/episodios.py: no los escribas a mano aqui.
-->
Película de {duracion} segundos ({minutos} minutos), hablada en {idioma_origen}.
Transcripción con timestamps absolutos del fuente; las líneas «sin diálogo» marcan tramos
sin habla:

{timeline}

Divide la película en una serie de episodios.

- Cada episodio dura entre {duracion_min} y {duracion_max} segundos (objetivo {duracion_objetivo}).
- Como máximo {max_episodios} episodios. Devuelve los que el material dé de sí: menos
  episodios buenos siempre es mejor que estirar la serie con relleno.
- Los episodios NO pueden cubrir más del {cobertura_max} % de la película: deja fuera el
  material que no aporta.
- Orden cronológico estricto, sin solapes.
- Para cada episodio: inicio < cumbre < desenlace < fin, con al menos {cola_minima} segundos
  entre `desenlace` y `fin` — ahí va el cierre en tensión.
- `titulo` sin numerar: el número de parte lo añade el sistema.
- `cliffhanger` del ÚLTIMO episodio: no dejes nada abierto, es el cierre de la historia.

Escribe titulo, razon, resumen, cliffhanger, tituloSerie y sinopsis en {idioma_salida}.
