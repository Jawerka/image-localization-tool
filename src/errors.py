"""Исключения пайплайна обработки изображений."""


class PipelineError(Exception):
    """Базовая ошибка пайплайна."""

    def __init__(self, message: str, stage: str = "", recoverable: bool = False):
        super().__init__(message)
        self.stage = stage
        self.recoverable = recoverable


class CriticalPipelineError(PipelineError):
    """Критическая ошибка — обработка невозможна."""

    def __init__(self, message: str, stage: str = ""):
        super().__init__(message, stage=stage, recoverable=False)


class StageError(PipelineError):
    """Ошибка на отдельном этапе — может быть обработана fallback."""

    def __init__(self, message: str, stage: str = ""):
        super().__init__(message, stage=stage, recoverable=True)


class PipelineCancelled(PipelineError):
    """Обработка остановлена по запросу вызывающего кода."""

    def __init__(self, message: str = "Отменено", stage: str = ""):
        super().__init__(message, stage=stage, recoverable=False)
