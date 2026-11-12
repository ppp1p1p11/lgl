from sqlalchemy import func, select
from sqlalchemy.orm import Session

from legalos.auth.models import User
from legalos.seed import seed
from legalos.tenancy.models import Membership, Tenant


def test_seed_is_idempotent(owner_engine) -> None:
    for _ in range(2):
        with Session(owner_engine) as db, db.begin():
            seed(db)
    with Session(owner_engine) as db:
        assert db.scalar(select(func.count()).select_from(Tenant)) == 3
        assert (
            db.scalar(select(func.count()).select_from(User)) == 7
        )  # one person belongs to two firms
        assert db.scalar(select(func.count()).select_from(Membership)) == 8
