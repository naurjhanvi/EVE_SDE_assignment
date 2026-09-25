from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from starlette.concurrency import run_in_threadpool

from app.database import Base, engine, get_db
from app.cache import get_json, invalidate, set_json
from app.rate_limit import client_bucket_id, consume_request_limit
from app.config import settings
from app.models import Booking, DiagnosticCentre, DiagnosticTest, Payment, PaymentWebhookEvent, User, centre_tests
from app.schemas import (BookingCreate, BookingResponse, CentreCreate, CentreResponse, LoginRequest, OfferCreate,
                         PaymentCreate, PaymentResponse, PaymentWebhook, SignupRequest, TestCreate, TestOffering,
                         TokenResponse, UserResponse)
from app.security import create_access_token, hash_password, read_access_token, verify_password
from app.seed import ensure_admin_account, seed_catalog


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with Session(engine) as db:
        seed_catalog(db)
        ensure_admin_account(db)
    yield


app = FastAPI(title="EVE Healthcare Diagnostic Booking API", version="1.0.0", lifespan=lifespan)
bearer_scheme = HTTPBearer(auto_error=False)


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    if request.url.path in {"/health", "/docs", "/redoc", "/openapi.json"}:
        return await call_next(request)

    path = request.url.path
    if path.startswith("/auth/"):
        bucket, limit = "auth", settings.rate_limit_auth_requests
    elif path.startswith("/payments"):
        bucket, limit = "payments", settings.rate_limit_payment_requests
    else:
        bucket, limit = "api", settings.rate_limit_requests

    client_host = request.client.host if request.client else "unknown"
    key = f"ratelimit:v1:{bucket}:{client_bucket_id(client_host)}"
    count, retry_after = await run_in_threadpool(
        consume_request_limit, key, settings.rate_limit_window_seconds
    )
    remaining = max(0, limit - count)
    headers = {"X-RateLimit-Limit": str(limit), "X-RateLimit-Remaining": str(remaining)}
    if count > limit:
        headers["Retry-After"] = str(retry_after)
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please retry later."}, headers=headers)

    response = await call_next(request)
    response.headers.update(headers)
    return response


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
                 db: Session = Depends(get_db)) -> User:
    user_id = read_access_token(credentials.credentials) if credentials else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"})
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    normalized_email = str(payload.email).lower()
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    configured_admin_email = settings.admin_email.strip().lower()
    user = User(name=payload.name.strip(), email=normalized_email, password_hash=hash_password(payload.password),
                is_admin=bool(configured_admin_email and normalized_email == configured_admin_email))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    db.refresh(user)
    return user


@app.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})
    return TokenResponse(access_token=create_access_token(user.id))


@app.get("/auth/me", response_model=UserResponse)
def get_current_user_profile(user: User = Depends(current_user)):
    return user


@app.get("/centres", response_model=list[CentreResponse])
def list_centres(db: Session = Depends(get_db)):
    cache_key = "catalog:centres:v1"
    cached = get_json(cache_key)
    if cached is not None:
        return [CentreResponse.model_validate(item) for item in cached]
    centres = db.scalars(select(DiagnosticCentre).options(joinedload(DiagnosticCentre.tests)).order_by(DiagnosticCentre.name)).unique().all()
    result = []
    for centre in centres:
        offerings = []
        for test in centre.tests:
            price = db.execute(select(centre_tests.c.price).where(
                centre_tests.c.centre_id == centre.id, centre_tests.c.test_id == test.id
            )).scalar_one()
            offerings.append(TestOffering(id=test.id, name=test.name, description=test.description, price=price))
        result.append(CentreResponse(id=centre.id, name=centre.name, location=centre.location, tests=offerings))
    set_json(cache_key, [centre.model_dump(mode="json") for centre in result], ttl_seconds=60)
    return result


@app.post("/centres", response_model=CentreResponse, status_code=status.HTTP_201_CREATED)
def create_centre(payload: CentreCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    centre = DiagnosticCentre(name=payload.name.strip(), location=payload.location.strip())
    db.add(centre)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A centre with this name already exists")
    db.refresh(centre)
    invalidate("catalog:centres:v1")
    return CentreResponse(id=centre.id, name=centre.name, location=centre.location, tests=[])


@app.post("/tests", status_code=status.HTTP_201_CREATED)
def create_test(payload: TestCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    test = DiagnosticTest(name=payload.name.strip(), description=payload.description.strip())
    db.add(test)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A test with this name already exists")
    db.refresh(test)
    invalidate("catalog:centres:v1")
    return {"id": test.id, "name": test.name, "description": test.description}


@app.put("/centres/{centre_id}/tests", status_code=status.HTTP_204_NO_CONTENT)
def offer_test(centre_id: int, payload: OfferCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if db.get(DiagnosticCentre, centre_id) is None:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    if db.get(DiagnosticTest, payload.test_id) is None:
        raise HTTPException(status_code=404, detail="Diagnostic test not found")
    existing = db.execute(select(centre_tests).where(
        centre_tests.c.centre_id == centre_id, centre_tests.c.test_id == payload.test_id
    )).first()
    if existing:
        db.execute(centre_tests.update().where(
            centre_tests.c.centre_id == centre_id, centre_tests.c.test_id == payload.test_id
        ).values(price=payload.price))
    else:
        db.execute(centre_tests.insert().values(centre_id=centre_id, test_id=payload.test_id, price=payload.price))
    db.commit()
    invalidate("catalog:centres:v1")


@app.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(payload: BookingCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.get(DiagnosticCentre, payload.centre_id) is None:
        raise HTTPException(status_code=404, detail="Diagnostic centre not found")
    price = db.execute(select(centre_tests.c.price).where(
        centre_tests.c.centre_id == payload.centre_id, centre_tests.c.test_id == payload.test_id
    )).scalar_one_or_none()
    if price is None:
        raise HTTPException(status_code=400, detail="This test is not offered at the selected centre")
    if payload.appointment_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Appointment must be in the future")
    booking = Booking(patient_id=user.id, centre_id=payload.centre_id, test_id=payload.test_id,
                      appointment_at=payload.appointment_at, amount=price, status="PENDING")
    db.add(booking)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This appointment slot has already been booked")
    db.refresh(booking)
    return booking


@app.get("/bookings", response_model=list[BookingResponse])
def list_bookings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(select(Booking).where(Booking.patient_id == user.id).order_by(Booking.created_at.desc())).all()


@app.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.patient_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this booking")
    return booking


@app.post("/bookings/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking(booking_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.patient_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this booking")
    if booking.status not in {"PENDING", "FAILED"}:
        raise HTTPException(status_code=409, detail="Only pending or failed bookings can be cancelled")
    booking.status = "CANCELLED"
    db.commit()
    db.refresh(booking)
    return booking


@app.post("/payments/", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(payload: PaymentCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking = db.get(Booking, payload.booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.patient_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this booking")
    existing = db.scalar(select(Payment).where(Payment.booking_id == booking.id,
                                               Payment.idempotency_key == payload.idempotency_key))
    if existing is not None:
        return existing
    if booking.status not in {"PENDING", "FAILED"}:
        raise HTTPException(status_code=409, detail="Only pending or failed bookings can be paid")
    payment = Payment(booking_id=booking.id, idempotency_key=payload.idempotency_key,
                      amount=booking.amount, status="FAILED" if payload.simulate_failure else "SUCCESS")
    db.add(payment)
    booking.status = "FAILED" if payload.simulate_failure else "CONFIRMED"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Payment).where(Payment.booking_id == booking.id,
                                                   Payment.idempotency_key == payload.idempotency_key))
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail="Payment could not be created")
    db.refresh(payment)
    return payment


@app.post("/payments/webhook/")
def payment_webhook(payload: PaymentWebhook, db: Session = Depends(get_db)):
    prior = db.get(PaymentWebhookEvent, payload.event_id)
    if prior is not None:
        if prior.payment_id != payload.payment_id or prior.status != payload.status:
            raise HTTPException(status_code=409, detail="Event ID was already used with a different payload")
        return {"received": True, "duplicate": True}
    payment = db.get(Payment, payload.payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    booking = db.get(Booking, payment.booking_id)
    db.add(PaymentWebhookEvent(event_id=payload.event_id, payment_id=payment.id, status=payload.status))
    payment.status = payload.status
    booking.status = "CONFIRMED" if payload.status == "SUCCESS" else "FAILED"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        prior = db.get(PaymentWebhookEvent, payload.event_id)
        if prior and prior.payment_id == payload.payment_id and prior.status == payload.status:
            return {"received": True, "duplicate": True}
        raise HTTPException(status_code=409, detail="Webhook event could not be recorded")
    return {"received": True, "duplicate": False}
