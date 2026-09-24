# Guia de Contribucion (Contributing Guidelines)

Gracias por tu interes en contribuir a este proyecto Open Source. Tu ayuda es fundamental para hacer que el subtitulado y la traduccion en tiempo real sean accesibles para cualquier creador de contenido y streamer en el mundo.

---

## Flujo de Trabajo para Contribuir

1. **Fork del Repositorio:**
   Haz un fork del repositorio en tu cuenta de GitHub y clonalo localmente:
   ```bash
   git clone https://github.com/tu-usuario/live-subtitles-translator.git
   cd live-subtitles-translator
   ```

2. **Crear una Rama de Trabajo (*Feature Branch*):**
   Usa un nombre descriptivo para tu rama:
   ```bash
   git checkout -b feat/soporte-multi-idioma
   # o
   git checkout -b fix/latencia-vad-buffer
   ```

3. **Preparar el Entorno Local:**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

4. **Realizar Cambios y Pruebas Locales:**
   Verifica que la integracion funcione antes de hacer commit:
   ```bash
   ./start.sh
   ./venv/bin/python worker.py --file sample_jfk.wav
   ./stop.sh
   ```

5. **Hacer Commit Siguiendo Conventional Commits:**
   Seguimos la especificacion de [Conventional Commits](https://www.conventionalcommits.org/):
   - `feat: agregar selector dinamico de idiomas en la UI`
   - `fix: resolver desincronizacion de timestamps en modo overlay`
   - `docs: actualizar instrucciones para OBS Studio en macOS`
   - `perf: reducir tiempo de inicializacion de Silero VAD`
   - `refactor: modularizar gestor de WebSockets`

6. **Enviar Pull Request (PR):**
   - Haz push a tu fork: `git push origin mi-rama`.
   - Abre un Pull Request describiendo claramente:
     - El problema o funcionalidad abordada.
     - Pruebas realizadas para comprobar el funcionamiento.
     - Capturas de pantalla o logs si aplica.

---

## Reporte de Errores (Bug Reports)

Si encuentras un bug, por favor abre un *Issue* en GitHub incluyendo:
1. Sistema Operativo y version (Linux, macOS, Windows).
2. Version de Python y de Docker (si aplica).
3. Dispositivo de audio utilizado o archivo WAV de prueba.
4. Logs de consola del worker o del servidor.
5. Pasos exactos para reproducir el comportamiento.

---

## Ideas y Mejoras Bienvenidas
- Soporte para nuevos pares de idiomas (ej. Frances, Aleman, Portugues).
- Modos de visualizacion adicionales para vlogging o podcasts.
- Integracion con modelos locales de ASR / LLM (ej. Whisper.cpp u Ollama).
- Empaquetado en binario standalone / ejecutable de escritorio.
