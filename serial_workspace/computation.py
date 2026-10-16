"""One in-flight DSP job per panel; stale results are ignored without queuing snapshots."""

from PySide6 import QtCore


class Signals(QtCore.QObject):
    finished = QtCore.Signal(int, object, str)


class Job(QtCore.QRunnable):
    def __init__(self, generation, operation):
        super().__init__()
        self.generation = generation
        self.operation = operation
        self.signals = Signals()

    def run(self):
        try:
            result = self.operation()
        except Exception as exc:
            self.signals.finished.emit(self.generation, None, str(exc))
        else:
            self.signals.finished.emit(self.generation, result, "")


class LatestComputation(QtCore.QObject):
    ready = QtCore.Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QtCore.QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.generation = 0
        self.job = None

    def invalidate(self):
        self.generation += 1

    def submit(self, operation):
        if self.job is not None:
            return False
        self.job = Job(self.generation, operation)
        self.job.signals.finished.connect(self._finished)
        self.pool.start(self.job)
        return True

    @QtCore.Slot(int, object, str)
    def _finished(self, generation, result, error):
        self.job = None
        if generation == self.generation:
            self.ready.emit(result, error)

    def stop(self):
        self.invalidate()
        self.pool.waitForDone()
