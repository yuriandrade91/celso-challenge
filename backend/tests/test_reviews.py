from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import get_current_user
from app.database import Base, get_db
from app.domain.review_exceptions import ReviewRequestConflictError
from app.models import StudentModel
from app.repositories.reviews import ReviewRepository
from app.routers.reviews import router as reviews_router
from app.schemas.auth import AuthenticatedUser
from app.schemas.reviews import ReviewDecision, ReviewRequestCreate
from app.services.reviews import ReviewService


@pytest.fixture
def review_service() -> Iterator[ReviewService]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(
            StudentModel(
                student_id="student-1",
                name="Ana Silva",
                email="ana@example.com",
                math_grade=12,
                history_grade=15,
                review_requested=False,
            )
        )
        db.commit()
        yield ReviewService(ReviewRepository(db))
    engine.dispose()


def test_student_can_request_review_with_justification(
    review_service: ReviewService,
) -> None:
    review, student = review_service.request_review(
        "student-1",
        ReviewRequestCreate(
            subject="math",
            justification="Acredito que houve um erro na correção.",
        ),
    )

    assert review.subject == "math"
    assert review.justification == "Acredito que houve um erro na correção."
    assert review.original_grade == 12
    assert review.status == "pending"
    assert student.math_grade == 12
    assert student.review_requested is True


def test_only_one_pending_review_per_student_and_subject(
    review_service: ReviewService,
) -> None:
    request = ReviewRequestCreate(
        subject="history",
        justification="Gostaria de rever a correção da questão dois.",
    )
    review_service.request_review("student-1", request)

    with pytest.raises(ReviewRequestConflictError):
        review_service.request_review("student-1", request)


def test_teacher_adjustment_updates_grade_and_closes_request(
    review_service: ReviewService,
) -> None:
    review, _ = review_service.request_review(
        "student-1",
        ReviewRequestCreate(
            subject="math",
            justification="Acredito que houve um erro na correção.",
        ),
    )

    decided, student = review_service.decide_review(
        review.id,
        ReviewDecision(
            action="adjusted",
            teacher_response="Após rever, a nota foi corrigida.",
            adjusted_grade=14,
        ),
    )

    assert decided.status == "adjusted"
    assert decided.adjusted_grade == 14
    assert decided.teacher_response == "Após rever, a nota foi corrigida."
    assert student.math_grade == 14
    assert student.review_requested is False


def test_teacher_cancellation_closes_request_without_changing_grade(
    review_service: ReviewService,
) -> None:
    review, _ = review_service.request_review(
        "student-1",
        ReviewRequestCreate(
            subject="history",
            justification="Gostaria de rever a correção da questão dois.",
        ),
    )

    decided, student = review_service.decide_review(
        review.id,
        ReviewDecision(
            action="cancelled",
            teacher_response="A nota está correta conforme os critérios.",
        ),
    )

    assert decided.status == "cancelled"
    assert decided.adjusted_grade is None
    assert student.history_grade == 15
    assert student.review_requested is False


def test_teacher_can_delete_pending_request(review_service: ReviewService) -> None:
    review, student = review_service.request_review(
        "student-1",
        ReviewRequestCreate(
            subject="history",
            justification="Gostaria de rever a correção da questão dois.",
        ),
    )

    review_service.delete_pending_review(review.id)

    assert review_service.get_student_reviews("student-1") == []
    assert student.review_requested is False


def test_teacher_cannot_delete_a_decided_request(review_service: ReviewService) -> None:
    review, _ = review_service.request_review(
        "student-1",
        ReviewRequestCreate(
            subject="history",
            justification="Gostaria de rever a correção da questão dois.",
        ),
    )
    review_service.decide_review(
        review.id,
        ReviewDecision(
            action="cancelled",
            teacher_response="A nota está correta conforme os critérios.",
        ),
    )

    with pytest.raises(ReviewRequestConflictError):
        review_service.delete_pending_review(review.id)


def test_review_endpoints_enforce_roles_and_allow_teacher_decision() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as db:
        db.add(
            StudentModel(
                student_id="student-1",
                name="Ana Silva",
                email="ana@example.com",
                math_grade=12,
                history_grade=15,
                review_requested=False,
            )
        )
        db.commit()

    app = FastAPI()
    app.include_router(reviews_router)
    current_user = [
        AuthenticatedUser(
            email="ana@example.com",
            role="student",
            student_id="student-1",
        )
    ]

    def override_db() -> Iterator[Session]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: current_user[0]
    with TestClient(app) as client:
        created = client.post(
            "/reviews/",
            json={
                "subject": "math",
                "justification": "Acredito que houve um erro na correção.",
            },
        )
        assert created.status_code == 201
        assert created.json()["data"]["status"] == "pending"
        created_second = client.post(
            "/reviews/",
            json={
                "subject": "history",
                "justification": "Gostaria de rever a correção da questão dois.",
            },
        )
        assert created_second.status_code == 201
        assert len(client.get("/reviews/me").json()["data"]) == 2
        assert client.get("/reviews/").status_code == 403

        current_user[0] = AuthenticatedUser(
            email="professor@example.com",
            role="teacher",
        )
        assert client.get("/reviews/me").status_code == 403
        assert client.post(
            "/reviews/",
            json={
                "subject": "history",
                "justification": "Acredito que houve um erro na correção.",
            },
        ).status_code == 403
        pending = client.get("/reviews/")
        assert pending.status_code == 200
        review_id = next(
            review["id"]
            for review in pending.json()["data"]
            if review["subject"] == "math"
        )
        decided = client.patch(
            f"/reviews/{review_id}/decision",
            json={
                "action": "adjusted",
                "teacherResponse": "A correção foi atualizada.",
                "adjustedGrade": 14,
            },
        )
        pending_after_decision = client.get("/reviews/").json()["data"]
        assert len(pending_after_decision) == 1
        deleted = client.delete(
            f"/reviews/{pending_after_decision[0]['id']}"
        )
        assert deleted.status_code == 200
        assert client.get("/reviews/").json()["data"] == []

    assert decided.status_code == 200
    assert decided.json()["data"]["adjustedGrade"] == 14
    engine.dispose()
