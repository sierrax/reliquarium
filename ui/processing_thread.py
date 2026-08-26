"""Background thread that performs move/copy operations for selected rows."""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.file_ops import ConflictPolicy, Operation, perform_op


class ProcessingThread(QThread):
    progress = Signal(int, int)          # completed, total
    fileDone = Signal(int, object)        # row_index, OpResult
    finishedAll = Signal()

    def __init__(self, jobs: list[tuple[int, str, str]], operation: Operation,
                 conflict_policy: ConflictPolicy, parent=None):
        """jobs: list of (row_index, source_path, target_dir)"""
        super().__init__(parent)
        self.jobs = jobs
        self.operation = operation
        self.conflict_policy = conflict_policy
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        total = len(self.jobs)
        for i, (row_index, source_path, target_dir) in enumerate(self.jobs, start=1):
            if self._stop:
                break
            result = perform_op(source_path, target_dir, self.operation, self.conflict_policy)
            self.fileDone.emit(row_index, result)
            self.progress.emit(i, total)
        self.finishedAll.emit()
