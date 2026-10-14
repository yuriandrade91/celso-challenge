class StudentAlreadyExistsError(Exception):
    def __init__(
        self,
        message: str = "Student ID or email is already registered.",
        field: str = "studentId",
    ) -> None:
        super().__init__(message)
        self.field = field


class StudentNotFoundError(Exception):
    def __init__(self, student_id: str) -> None:
        super().__init__(student_id)
        self.field = "studentId"


class ConfigurationError(ValueError):
    """Configuração do servidor inválida: falha do operador, não do cliente."""


class RosterConflictError(Exception):
    """A linha do CSV contradiz o cadastro de alunos (mensagem sem PII)."""
