"""Agrupa ráfagas de avisos sin retener el cerrojo del reloj en cada respuesta.

El contenido de los informes se conserva al entrar. Solo la proyección de pantalla
se agrupa hasta el siguiente refresco (máximo 100 ms mientras el proceso está vivo).
"""
import threading
import time


class StateRefresh:
    def __init__(self, session):
        self.session = session
        self.pending = False
        self.timer = None
        self.last = 0.0

    def request(self):
        with self.session.lock:
            self.pending = True
            if self.timer is None:
                self.timer = threading.Timer(.1, self.flush)
                self.timer.daemon = True
                self.timer.start()

    def flush(self):
        with self.session.lock:
            self.timer = None
            if self.pending and not self.session._stop.is_set():
                self.pending = False
                self.session._rebuild()
                self.last = time.monotonic()

    def close(self):
        with self.session.lock:
            if self.timer:
                self.timer.cancel()
                self.timer = None
            self.pending = False
