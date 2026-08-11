# Plantillas de prompt

Este es el texto que el modelo lee. Vive aquí, en markdown, y no dentro del código Python,
por una razón concreta: **es lo que más se toca y lo que menos tiene que ver con programar**.
Refinar cómo se cuenta una historia no debería obligar a abrir un `.py` ni a entender un
f-string.

## Cómo se editan

Se editan. Sin más. El código los carga en cada ejecución.

Lo único que no se puede tocar libremente son los **marcadores** `{nombre}`: el código los
sustituye por valores reales antes de enviar el prompt. Si escribes uno que no existe, la
carga falla con el nombre del marcador y la lista de los válidos — falla al arrancar, no a
mitad de una serie.

| Archivo | Cuándo se usa | Marcadores |
|---|---|---|
| `serie.sistema.md` | Decidir dónde cortar la película | *(ninguno)* |
| `serie.usuario.md` | Idem, con el material concreto | ver cabecera del archivo |
| `guion.sistema.md` | Escribir el guion de un episodio | ver cabecera del archivo |
| `guion.usuario.md` | Idem, con el material del episodio | ver cabecera del archivo |

Los valores numéricos —duraciones, porcentajes, ritmo de habla— **no se escriben a mano**:
llegan como marcadores desde las constantes del dominio (`dominio/episodios.py`,
`dominio/tramos.py`). Así el prompt no puede prometerle al modelo un límite distinto del que
el código va a exigirle después, que es como se llega a que el guion se recorte solo.

## Cómo saber si un cambio mejora

```bash
python -m viralfarm.banco generar media/<video> --episodios 2
python -m viralfarm.banco comparar media/banco/<version-a> media/banco/<version-b>
```

`generar` escribe en `media/banco/<hash-sistema>+<hash-usuario>/`: **la carpeta es la
versión**. Editar un `.md` y volver a generar produce otra carpeta, y las dos quedan
comparables sin llevar la cuenta a mano. Cuesta una llamada por episodio — céntimos.

La tabla saca densidad de voz, aire muerto, dispersión de duración de tramos, fronteras
redondas y longitud de los textos, y dice en qué dirección se movió cada una. Un refinamiento
que no mueve ninguna probablemente no ha hecho nada; uno que las mueve a peor conviene saberlo
antes de renderizar una hora de vídeo.

Ejemplo real, la primera versión en markdown contra la salida del pipeline TypeScript:

```
  densidad de voz               -7.8%  peor
  brecha declarada-real         -8.7%  mejor
  aire muerto por episodio       -29s  mejor
  fronteras redondas             -25%  mejor
  dispersión de tramos           +3.7  mejor
```

Se acabó el metrónomo y el reparto por enteros, pero el episodio narra todavía menos que
antes: la primera cifra es la que queda por resolver, y es la que depende de qué se le pida
al guionista en estos archivos.

Sin `voz.json` la densidad se **estima** desde el ritmo de habla del idioma, así que el aire
muerto que reporta es un suelo: el real es igual o menor. Sirve para ordenar dos versiones,
no para prometer un número.

## Qué está medido y qué no

Las cifras que aparecen en los comentarios de los prompts salen de la primera serie generada
con un modelo real (2026-08-06, DeepSeek, `pelicula-prueba-05-25`). No son ejemplos
inventados:

- La narración real ocupaba el **13,3 %** y el **19,0 %** del episodio, no el 38 % y el 27 %
  que el sistema declaraba.
- Un tramo de **16,4 s contenía 4,1 s de voz**.
- **19 de 27** fronteras de tramo eran enteros redondos.
- Hubo un hueco de **58 s** sin voz ni diálogo en el primer minuto del primer episodio.

Si un cambio de prompt pretende arreglar alguno de esos síntomas, el banco de pruebas lo
dirá con el mismo número.
