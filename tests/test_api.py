def test_signup_login_and_catalog(client):
    assert client.post("/auth/signup", json={"name": "Asha", "email": "asha@example.com", "password": "correct-horse-8"}).status_code == 201
    assert client.post("/auth/login", json={"email": "asha@example.com", "password": "correct-horse-8"}).status_code == 200
    centres = client.get("/centres").json()
    assert len(centres) >= 1
    assert centres[0]["tests"]


def test_current_user_profile_reports_server_role(client, auth_headers):
    response = client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "asha@example.com"
    assert response.json()["is_admin"] is False


def test_booking_requires_auth_and_uses_catalog_price(client, booking_payload, auth_headers):
    assert client.post("/bookings", json=booking_payload).status_code == 401
    response = client.post("/bookings", json=booking_payload, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["status"] == "PENDING"
    assert float(response.json()["amount"]) > 0


def test_payment_success_and_idempotent_retry(client, booking_payload, auth_headers):
    booking = client.post("/bookings", json=booking_payload, headers=auth_headers).json()
    payload = {"booking_id": booking["id"], "idempotency_key": "checkout-1"}
    first = client.post("/payments/", json=payload, headers=auth_headers)
    second = client.post("/payments/", json=payload, headers=auth_headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"/bookings/{booking['id']}", headers=auth_headers).json()["status"] == "CONFIRMED"


def test_failed_payment_and_webhook_replay(client, booking_payload, auth_headers):
    booking = client.post("/bookings", json=booking_payload, headers=auth_headers).json()
    payment = client.post("/payments/", json={"booking_id": booking["id"], "idempotency_key": "checkout-2",
        "simulate_failure": True}, headers=auth_headers).json()
    event = {"event_id": "provider-event-1", "payment_id": payment["id"], "status": "SUCCESS"}
    assert client.post("/payments/webhook/", json=event).json() == {"received": True, "duplicate": False}
    assert client.post("/payments/webhook/", json=event).json() == {"received": True, "duplicate": True}
    assert client.get(f"/bookings/{booking['id']}", headers=auth_headers).json()["status"] == "CONFIRMED"


def test_users_cannot_read_each_others_bookings(client, booking_payload, auth_headers):
    booking = client.post("/bookings", json=booking_payload, headers=auth_headers).json()
    client.post("/auth/signup", json={"name": "Dev", "email": "dev@example.com", "password": "correct-horse-9"})
    token = client.post("/auth/login", json={"email": "dev@example.com", "password": "correct-horse-9"}).json()["access_token"]
    response = client.get(f"/bookings/{booking['id']}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_invalid_booking_and_unoffered_test_are_rejected(client, booking_payload, auth_headers):
    assert client.get("/bookings/999", headers=auth_headers).status_code == 404
    booking_payload["test_id"] = 999
    assert client.post("/bookings", json=booking_payload, headers=auth_headers).status_code == 400


def test_webhook_rejects_reused_event_id_with_changed_payload(client, booking_payload, auth_headers):
    booking = client.post("/bookings", json=booking_payload, headers=auth_headers).json()
    payment = client.post("/payments/", json={"booking_id": booking["id"], "idempotency_key": "checkout-3"},
                          headers=auth_headers).json()
    event = {"event_id": "provider-event-conflict", "payment_id": payment["id"], "status": "SUCCESS"}
    assert client.post("/payments/webhook/", json=event).status_code == 200
    changed_event = {**event, "status": "FAILED"}
    assert client.post("/payments/webhook/", json=changed_event).status_code == 409


def test_same_centre_test_slot_cannot_be_booked_twice_but_cancel_releases_it(client, booking_payload, auth_headers):
    first = client.post("/bookings", json=booking_payload, headers=auth_headers)
    assert first.status_code == 201
    assert client.post("/bookings", json=booking_payload, headers=auth_headers).status_code == 409
    cancelled = client.post(f"/bookings/{first.json()['id']}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    assert client.post("/bookings", json=booking_payload, headers=auth_headers).status_code == 201


def test_failed_booking_can_be_paid_again_with_new_idempotency_key(client, booking_payload, auth_headers):
    booking = client.post("/bookings", json=booking_payload, headers=auth_headers).json()
    first = client.post("/payments/", json={"booking_id": booking["id"], "idempotency_key": "attempt-1",
        "simulate_failure": True}, headers=auth_headers)
    assert first.json()["status"] == "FAILED"
    retry = client.post("/payments/", json={"booking_id": booking["id"], "idempotency_key": "attempt-2"},
                        headers=auth_headers)
    assert retry.status_code == 201
    assert retry.json()["status"] == "SUCCESS"
    assert client.get(f"/bookings/{booking['id']}", headers=auth_headers).json()["status"] == "CONFIRMED"


def test_rate_limit_returns_429_and_retry_after(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "consume_request_limit", lambda key, window: (121, 35))
    response = client.get("/centres")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "35"
