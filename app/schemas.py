from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    is_admin: bool
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TestOffering(BaseModel):
    id: int
    name: str
    description: str
    price: Decimal


class CentreResponse(BaseModel):
    id: int
    name: str
    location: str
    tests: list[TestOffering]


class CentreCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    location: str = Field(min_length=2, max_length=255)


class TestCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=500)


class OfferCreate(BaseModel):
    test_id: int = Field(gt=0)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class BookingCreate(BaseModel):
    centre_id: int = Field(gt=0)
    test_id: int = Field(gt=0)
    appointment_at: datetime

    @field_validator("appointment_at")
    @classmethod
    def appointment_must_have_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("appointment_at must include a timezone")
        return value


class BookingResponse(BaseModel):
    id: int
    patient_id: int
    centre_id: int
    test_id: int
    appointment_at: datetime
    amount: Decimal
    status: str
    model_config = ConfigDict(from_attributes=True)


class PaymentCreate(BaseModel):
    booking_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    simulate_failure: bool = False


class PaymentResponse(BaseModel):
    id: int
    booking_id: int
    amount: Decimal
    status: str
    model_config = ConfigDict(from_attributes=True)


class PaymentWebhook(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    payment_id: int = Field(gt=0)
    status: Literal["SUCCESS", "FAILED"]
