from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String,
                        Table, Column, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


centre_tests = Table(
    "centre_tests",
    Base.metadata,
    Column("centre_id", ForeignKey("diagnostic_centres.id", ondelete="CASCADE"), primary_key=True),
    Column("test_id", ForeignKey("diagnostic_tests.id", ondelete="CASCADE"), primary_key=True),
    Column("price", Numeric(10, 2), nullable=False),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    bookings: Mapped[list["Booking"]] = relationship(back_populates="patient")


class DiagnosticCentre(Base):
    __tablename__ = "diagnostic_centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    location: Mapped[str] = mapped_column(String(255))
    tests: Mapped[list["DiagnosticTest"]] = relationship(secondary=centre_tests, back_populates="centres")


class DiagnosticTest(Base):
    __tablename__ = "diagnostic_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")
    centres: Mapped[list[DiagnosticCentre]] = relationship(secondary=centre_tests, back_populates="tests")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'FAILED', 'CANCELLED')", name="ck_booking_status"),
        Index(
            "uq_active_booking_slot", "centre_id", "test_id", "appointment_at", unique=True,
            postgresql_where=text("status <> 'CANCELLED'"),
            sqlite_where=text("status <> 'CANCELLED'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_centres.id"))
    test_id: Mapped[int] = mapped_column(ForeignKey("diagnostic_tests.id"))
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    patient: Mapped[User] = relationship(back_populates="bookings")
    centre: Mapped[DiagnosticCentre] = relationship()
    test: Mapped[DiagnosticTest] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="booking")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("booking_id", "idempotency_key", name="uq_payment_booking_idempotency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    booking: Mapped[Booking] = relationship(back_populates="payments")
    events: Mapped[list["PaymentWebhookEvent"]] = relationship(back_populates="payment")


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    payment: Mapped[Payment] = relationship(back_populates="events")
