class ReviewRequestNotFoundError(Exception):
    def __init__(self, review_id: int) -> None:
        super().__init__(str(review_id))


class ReviewRequestConflictError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
