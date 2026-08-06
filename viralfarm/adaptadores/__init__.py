"""Todo lo que habla con el exterior: LLM, ffmpeg, whisper, TTS.

Los adaptadores son la única capa que hace red, disco o subprocesos. El dominio no los
importa; los pasos los reciben ya construidos. Así el dominio se testea sin nada instalado y
cambiar de proveedor no toca la lógica de negocio.
"""
