"""Lógica de negocio pura.

**Regla del paquete: nada de aquí toca disco, red ni configuración.** Ni un `open()`, ni un
`subprocess`, ni un `import viralfarm.config`. Todo entra por parámetros y sale por retorno.

Es lo que hace que el 70 % del sistema se pueda testear sin ffmpeg, sin claves de API y sin
artefactos — el problema que hacía imposible verificar el pipeline TypeScript salvo
renderizando 18 minutos de video.
"""
