from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DiagnosticCentre, DiagnosticTest, centre_tests
from app.models import User
from app.security import hash_password


SEED_CENTRES = [
    {"name": "EVE Central Diagnostics", "location": "Indiranagar, Bengaluru", "tests": {"Complete Blood Count (CBC)": 450, "Lipid Profile": 850, "Thyroid Profile (T3, T4, TSH)": 700}},
    {"name": "EVE Health Labs - Koramangala", "location": "Koramangala, Bengaluru", "tests": {"Complete Blood Count (CBC)": 500, "Lipid Profile": 900, "HbA1c": 600}},
    {"name": "EVE Diagnostics - Whitefield", "location": "Whitefield, Bengaluru", "tests": {"Thyroid Profile (T3, T4, TSH)": 750, "HbA1c": 650, "Vitamin D": 1200}},
]

DESCRIPTIONS = {name: "Example catalogue item for demonstration; not medical advice." for name in (
    "Complete Blood Count (CBC)", "Lipid Profile", "Thyroid Profile (T3, T4, TSH)", "HbA1c", "Vitamin D"
)}


def seed_catalog(db: Session) -> None:
    for centre_data in SEED_CENTRES:
        centre = db.scalar(select(DiagnosticCentre).where(DiagnosticCentre.name == centre_data["name"]))
        if centre is None:
            centre = DiagnosticCentre(name=centre_data["name"], location=centre_data["location"])
            db.add(centre)
            db.flush()
        for test_name, price in centre_data["tests"].items():
            test = db.scalar(select(DiagnosticTest).where(DiagnosticTest.name == test_name))
            if test is None:
                test = DiagnosticTest(name=test_name, description=DESCRIPTIONS[test_name])
                db.add(test)
                db.flush()
            current_price = db.execute(
                select(centre_tests.c.price).where(
                    centre_tests.c.centre_id == centre.id, centre_tests.c.test_id == test.id
                )
            ).scalar_one_or_none()
            if current_price is None:
                db.execute(centre_tests.insert().values(centre_id=centre.id, test_id=test.id, price=price))
    db.commit()


def ensure_admin_account(db: Session) -> None:
    """Create/reset the explicitly configured local demo admin account."""
    email = settings.admin_email.strip().lower()
    if not email or not settings.admin_password:
        return

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(name="EVE Demo Admin", email=email,
                    password_hash=hash_password(settings.admin_password), is_admin=True)
        db.add(user)
    else:
        user.name = "EVE Demo Admin"
        user.password_hash = hash_password(settings.admin_password)
        user.is_admin = True
        user.is_active = True
    db.commit()
