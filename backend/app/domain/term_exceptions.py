class TermNotFoundError(Exception):
    def __init__(self, term_id: int) -> None:
        super().__init__(str(term_id))


class TermConflictError(Exception):
    """Regra de negócio do semestre violada (mensagem segura para o cliente)."""
