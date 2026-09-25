"""Interactive terminal walkthrough and API edge-case checks for the EVE demo."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta
from getpass import getpass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit


API_BASE = "http://localhost:8000"
passed = 0
failed = 0


def request(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except HTTPError as error:
        raw = error.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return error.code, parsed
    except URLError as error:
        raise RuntimeError(f"Could not connect to {API_BASE}: {error.reason}") from error


def check(label: str, actual: int, expected: int) -> bool:
    global passed, failed
    ok = actual == expected
    if ok:
        passed += 1
        print(f"[PASS] {label} (HTTP {actual})")
    else:
        failed += 1
        print(f"[FAIL] {label}: expected HTTP {expected}, got HTTP {actual}")
    return ok


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or (default or "")


def ask_api_base() -> str:
    while True:
        value = ask("API base URL (press Enter to use the local default)", API_BASE)
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return value.rstrip("/")
        print("That doesn't look like a URL. Enter a full URL such as http://localhost:8000, or press Enter for the default.")


def select_catalog_item(items: list, label: str):
    while True:
        choice = ask(f"Choose {label} number", "1")
        try:
            index = int(choice) - 1
            if 0 <= index < len(items):
                return items[index]
        except ValueError:
            pass
        print(f"Enter a number from 1 to {len(items)}.")


def load_catalog():
    status, centres = request("GET", "/centres")
    if status != 200 or not centres:
        raise RuntimeError(f"Could not load diagnostic centres (HTTP {status}): {centres}")
    available = [centre for centre in centres if centre.get("tests")]
    if not available:
        raise RuntimeError("No centres currently offer any tests.")
    print("\nAvailable diagnostic centres:")
    for index, centre in enumerate(available, 1):
        print(f"  {index}. {centre['name']} - {centre['location']}")
        for test in centre["tests"]:
            print(f"       {test['name']}: ₹{test['price']}")
    centre = select_catalog_item(available, "centre")
    tests = centre["tests"]
    print(f"\nTests offered by {centre['name']}:")
    for index, test in enumerate(tests, 1):
        print(f"  {index}. {test['name']} - ₹{test['price']}")
    test = select_catalog_item(tests, "test")
    print(f"\nSelected: {centre['name']} / {test['name']} / ₹{test['price']}")
    return centre, test


def show_catalog(centres: list):
    print("\nDiagnostic centres and their test offers:")
    for centre in centres:
        print(f"\n  Centre {centre['id']}: {centre['name']} - {centre['location']}")
        if not centre["tests"]:
            print("    No tests offered yet.")
        for test in centre["tests"]:
            print(f"    Test {test['id']}: {test['name']} - ₹{test['price']}")


def parse_appointment(prompt: str = "Appointment date and time (YYYY-MM-DD HH:MM, local time)") -> datetime:
    default = (datetime.now().astimezone() + timedelta(days=3)).replace(
        hour=10, minute=30, second=0, microsecond=0
    ).strftime("%Y-%m-%d %H:%M")
    local_timezone = datetime.now().astimezone().tzinfo
    while True:
        value = ask(prompt, default)
        try:
            appointment = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=local_timezone)
            if appointment <= datetime.now().astimezone():
                print("Choose a future appointment time.")
                continue
            return appointment
        except ValueError:
            print("Use YYYY-MM-DD HH:MM, for example 2026-09-30 10:30. The time is treated as local time.")


def iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def account_from_token(email: str, token: str, required_role: str | None = None, newly_registered: bool = False):
    status, profile = request("GET", "/auth/me", token=token)
    if status != 200:
        raise RuntimeError(f"Could not identify the signed-in account (HTTP {status}).")
    actual_role = "admin" if profile["is_admin"] else "patient"
    state = "New account created and signed in" if newly_registered else "Existing account recognized and signed in"
    print(f"{state} as {profile['name']} ({profile['email']}). Server role: {actual_role}.")
    if required_role and actual_role != required_role:
        raise RuntimeError(f"This flow requires a {required_role} account; this account is {actual_role}.")
    return email, token, profile


def authenticate_account(required_role: str | None = None, prompt_label: str | None = None):
    """Log in first; if credentials are not recognized, offer signup with them."""
    if prompt_label:
        print(f"\nSign in to {prompt_label}.")
    while True:
        email = ask("Email")
        password = getpass("Password (input hidden): ")
        status, result = request("POST", "/auth/login", {"email": email, "password": password})

        if status == 200 and result and "access_token" in result:
            return account_from_token(email, result["access_token"], required_role)

        if status == 429:
            raise RuntimeError(
                "Authentication is temporarily rate-limited. The edge-case tour deliberately "
                "triggers this check; wait about 60 seconds, then try again."
            )
        if status != 401:
            detail = result.get("detail", result) if isinstance(result, dict) else result
            raise RuntimeError(f"Login request failed (HTTP {status}): {detail}")

        print("Those credentials did not sign in. The email may be new, or the password may be incorrect.")
        if ask("Is this a new account? Register it with this email and password? (y/n)", "n").lower() not in {"y", "yes"}:
            continue

        name = ask("Your name")
        status, result = request("POST", "/auth/signup", {"name": name, "email": email, "password": password})
        if status == 201:
            status, login_result = request("POST", "/auth/login", {"email": email, "password": password})
            if status != 200 or not login_result or "access_token" not in login_result:
                raise RuntimeError(f"Account was created, but sign-in failed (HTTP {status}): {login_result}")
            return account_from_token(email, login_result["access_token"], required_role, newly_registered=True)
        if status == 409:
            print("That email is already registered. Re-enter the existing account password.")
            continue
        detail = result.get("detail", result) if isinstance(result, dict) else result
        raise RuntimeError(f"Account creation failed (HTTP {status}): {detail}")


def create_booking(token: str, centre_id: int, test_id: int, appointment: datetime):
    status, result = request("POST", "/bookings", {
        "centre_id": centre_id,
        "test_id": test_id,
        "appointment_at": iso(appointment),
    }, token)
    if status != 201:
        raise RuntimeError(f"Booking creation failed (HTTP {status}): {result}")
    return result


def normal_demo(account=None):
    centre, test = load_catalog()
    appointment = parse_appointment()
    email, token, _ = account or authenticate_account()

    print("\nBooking summary")
    print(f"  Centre:      {centre['name']}")
    print(f"  Test:        {test['name']}")
    print(f"  Amount:      ₹{test['price']}")
    print(f"  Appointment: {iso(appointment)}")
    if ask("Create this booking? (y/n)", "y").lower() not in {"y", "yes"}:
        print("Cancelled before creating the booking.")
        return

    booking = create_booking(token, centre["id"], test["id"], appointment)
    outcome = ask("Simulate payment failure? (y/n)", "n").lower() in {"y", "yes"}
    payment_key = f"terminal-{uuid.uuid4().hex}"
    status, payment = request("POST", "/payments/", {
        "booking_id": booking["id"],
        "idempotency_key": payment_key,
        "simulate_failure": outcome,
    }, token)
    if status != 201:
        raise RuntimeError(f"Payment failed (HTTP {status}): {payment}")
    if payment["status"] == "FAILED" and ask("Retry failed payment with a new key? (y/n)", "y").lower() in {"y", "yes"}:
        status, payment = request("POST", "/payments/", {
            "booking_id": booking["id"],
            "idempotency_key": f"terminal-retry-{uuid.uuid4().hex}",
        }, token)
        if status != 201:
            raise RuntimeError(f"Payment retry failed (HTTP {status}): {payment}")

    _, final_booking = request("GET", f"/bookings/{booking['id']}", token=token)
    print("\nFinal booking")
    print(f"  Booking ID:  {final_booking['id']}")
    print(f"  Patient:     {email}")
    print(f"  Centre:      {centre['name']}")
    print(f"  Test:        {test['name']}")
    print(f"  Amount:      ₹{final_booking['amount']}")
    print(f"  Appointment: {final_booking['appointment_at']}")
    print(f"  Payment:     {payment['status']}")
    print(f"  Booking:     {final_booking['status']}")


def manage_my_bookings(account=None):
    _, token, _ = account or authenticate_account(required_role="patient")
    status, bookings = request("GET", "/bookings", token=token)
    if status != 200:
        raise RuntimeError(f"Could not load your bookings (HTTP {status}): {bookings}")
    if not bookings:
        print("\nThis account has no bookings yet.")
        return

    centres_status, centres = request("GET", "/centres")
    centre_names = {centre["id"]: centre["name"] for centre in centres} if centres_status == 200 else {}
    print("\nYour bookings:")
    for booking in bookings:
        print(
            f"  ID {booking['id']} | Centre {centre_names.get(booking['centre_id'], booking['centre_id'])} "
            f"| Test ID {booking['test_id']} | {booking['appointment_at']} "
            f"| ₹{booking['amount']} | {booking['status']}"
        )
    cancellable = [booking for booking in bookings if booking["status"] in {"PENDING", "FAILED"}]
    if not cancellable:
        print("\nThere are no pending or failed bookings that can be cancelled.")
        return
    if ask("Cancel one of these pending/failed bookings? (y/n)", "n").lower() not in {"y", "yes"}:
        return
    choices = [str(booking["id"]) for booking in cancellable]
    booking_id = ask(f"Booking ID to cancel ({', '.join(choices)})")
    if booking_id not in choices:
        print("That ID is not one of your cancellable bookings.")
        return
    status, result = request("POST", f"/bookings/{booking_id}/cancel", token=token)
    if status != 200:
        raise RuntimeError(f"Cancellation failed (HTTP {status}): {result}")
    print(f"Booking {booking_id} is now {result['status']}; the appointment slot has been released.")


def admin_catalog_demo(account=None):
    email, token, profile = account or authenticate_account(required_role="admin")
    if not profile["is_admin"]:
        raise RuntimeError(f"Admin catalogue tools require an admin account; {email} is a patient account.")
    while True:
        print("\nAdmin catalogue tools")
        print("  1. List centres, tests, and prices")
        print("  2. Add a diagnostic centre")
        print("  3. Add a test and offer it at a centre")
        print("  4. Add a test to a centre or update its price")
        print("  5. Return to main menu")
        choice = ask("Choose an action", "1")

        if choice == "5":
            return
        if choice == "1":
            status, centres = request("GET", "/centres")
            if status != 200:
                raise RuntimeError(f"Could not load catalogue (HTTP {status}): {centres}")
            show_catalog(centres)
            continue
        if choice == "2":
            name = ask("New centre name")
            location = ask("Centre location")
            status, result = request("POST", "/centres", {"name": name, "location": location}, token)
            if status != 201:
                print(f"Could not add centre (HTTP {status}): {result}")
            else:
                print(f"Added centre {result['id']}: {result['name']}.")
            continue
        if choice not in {"3", "4"}:
            print("Choose a number from 1 to 5.")
            continue

        status, centres = request("GET", "/centres")
        if status != 200 or not centres:
            raise RuntimeError(f"Could not load centres (HTTP {status}): {centres}")
        show_catalog(centres)
        centre = select_catalog_item(centres, "centre")

        if choice == "3":
            name = ask("New test name")
            description = ask("Test description", "Demonstration catalogue item")
            status, test = request("POST", "/tests", {"name": name, "description": description}, token)
            if status != 201:
                print(f"Could not add test (HTTP {status}): {test}")
                continue
            print(f"Created test {test['id']}: {test['name']}.")
        else:
            tests_by_id = {}
            for item in centres:
                for offered_test in item["tests"]:
                    tests_by_id[offered_test["id"]] = offered_test
            tests = list(tests_by_id.values())
            if not tests:
                print("No tests exist in the catalogue yet. Use option 3 first.")
                continue
            print("\nTests currently known to the catalogue:")
            for index, test_item in enumerate(tests, 1):
                print(f"  {index}. Test {test_item['id']}: {test_item['name']}")
            test = select_catalog_item(tests, "test")

        while True:
            raw_price = ask("Price in INR")
            try:
                price = float(raw_price)
                if price > 0:
                    break
            except ValueError:
                pass
            print("Enter a valid amount greater than zero, such as 450 or 799.50.")

        status, result = request(
            "PUT", f"/centres/{centre['id']}/tests",
            {"test_id": test["id"], "price": price}, token,
        )
        if status != 204:
            print(f"Could not set the centre's test offer (HTTP {status}): {result}")
        else:
            print(f"{test['name']} is now offered at {centre['name']} for ₹{price:.2f}.")


def edge_case_tour(primary_account=None):
    global passed, failed
    passed = failed = 0
    centre, test = load_catalog()
    base_date = parse_appointment("Base future appointment for generated edge-case scenarios (YYYY-MM-DD HH:MM)")
    if primary_account and not primary_account[2]["is_admin"]:
        email_a, token_a, _ = primary_account
        print(f"\nUsing your signed-in patient account as test account A: {email_a}.")
    else:
        email_a, token_a, _ = authenticate_account(
            required_role="patient", prompt_label="the first patient test account"
        )

    while True:
        email_b, token_b, _ = authenticate_account(
            required_role="patient", prompt_label="a second patient account with a different email"
        )
        if email_b.lower() != email_a.lower():
            break
        print("Use a different email for account B; the ownership check needs two distinct patients.")
    print(f"\nTest accounts: {email_a}, {email_b}")

    valid = {"centre_id": centre["id"], "test_id": test["id"], "appointment_at": iso(base_date)}

    status, _ = request("POST", "/bookings", valid)
    check("Booking without authentication is denied", status, 401)

    status, _ = request("POST", "/centres", {"name": "Patient Cannot Add Centre", "location": "Demo"}, token_a)
    check("Patient cannot use admin catalogue endpoint", status, 403)

    status, _ = request("GET", "/bookings/999999999", token=token_a)
    check("Unknown booking ID returns not found", status, 404)

    invalid_centre = {**valid, "centre_id": 999999999, "appointment_at": iso(base_date + timedelta(minutes=1))}
    status, _ = request("POST", "/bookings", invalid_centre, token_a)
    check("Unknown centre is rejected", status, 404)

    unavailable_test = {**valid, "test_id": 999999999, "appointment_at": iso(base_date + timedelta(minutes=2))}
    status, _ = request("POST", "/bookings", unavailable_test, token_a)
    check("Test not offered by selected centre is rejected", status, 400)

    past = {**valid, "appointment_at": iso(datetime.now().astimezone() - timedelta(minutes=5))}
    status, _ = request("POST", "/bookings", past, token_a)
    check("Past appointment is rejected", status, 400)

    missing_timezone = {**valid, "appointment_at": base_date.replace(tzinfo=None).isoformat(timespec="seconds")}
    status, _ = request("POST", "/bookings", missing_timezone, token_a)
    check("Appointment without timezone is rejected", status, 422)

    slot = {**valid, "appointment_at": iso(base_date + timedelta(minutes=10))}
    first = create_booking(token_a, centre["id"], test["id"], datetime.fromisoformat(slot["appointment_at"]))
    status, _ = request("POST", "/bookings", slot, token_a)
    check("Second booking for same active slot is rejected", status, 409)
    status, cancelled = request("POST", f"/bookings/{first['id']}/cancel", token=token_a)
    check("Pending booking can be cancelled", status, 200)
    if status == 200:
        check("Cancelled booking has CANCELLED status", 200 if cancelled["status"] == "CANCELLED" else 500, 200)
    status, _ = request("POST", "/bookings", slot, token_a)
    check("Cancellation releases the slot", status, 201)

    owned = create_booking(token_a, centre["id"], test["id"], base_date + timedelta(minutes=20))
    status, _ = request("GET", f"/bookings/{owned['id']}", token=token_b)
    check("Other patient cannot read booking", status, 403)
    status, _ = request("POST", "/payments/", {"booking_id": owned["id"], "idempotency_key": "other-user"}, token_b)
    check("Other patient cannot pay for booking", status, 403)

    successful = create_booking(token_a, centre["id"], test["id"], base_date + timedelta(minutes=30))
    success_body = {"booking_id": successful["id"], "idempotency_key": f"success-{uuid.uuid4().hex}"}
    status, success_payment = request("POST", "/payments/", success_body, token_a)
    check("Payment succeeds", status, 201)
    status, replayed_payment = request("POST", "/payments/", success_body, token_a)
    check("Repeated payment key reuses original payment", status, 201)
    check("Repeated payment has same ID", 200 if replayed_payment["id"] == success_payment["id"] else 500, 200)
    status, _ = request("POST", f"/bookings/{successful['id']}/cancel", token=token_a)
    check("Confirmed booking cannot be cancelled", status, 409)

    failed_booking = create_booking(token_a, centre["id"], test["id"], base_date + timedelta(minutes=40))
    failed_key = f"failed-{uuid.uuid4().hex}"
    status, failed_payment = request("POST", "/payments/", {
        "booking_id": failed_booking["id"], "idempotency_key": failed_key, "simulate_failure": True,
    }, token_a)
    check("Simulated payment failure is recorded", status, 201)
    check("Failed payment reports FAILED", 200 if failed_payment["status"] == "FAILED" else 500, 200)
    status, failed_replay = request("POST", "/payments/", {
        "booking_id": failed_booking["id"], "idempotency_key": failed_key,
    }, token_a)
    check("Retry with same key replays failed payment", status, 201)
    check("Same key does not create another payment", 200 if failed_replay["id"] == failed_payment["id"] else 500, 200)
    status, retry_payment = request("POST", "/payments/", {
        "booking_id": failed_booking["id"], "idempotency_key": f"retry-{uuid.uuid4().hex}",
    }, token_a)
    check("Failed booking can be retried with new key", status, 201)
    status, final_failed_booking = request("GET", f"/bookings/{failed_booking['id']}", token=token_a)
    check("Successful retry confirms original booking", 200 if final_failed_booking["status"] == "CONFIRMED" else 500, 200)

    event = {"event_id": f"event-{uuid.uuid4().hex}", "payment_id": retry_payment["id"], "status": "SUCCESS"}
    status, first_event = request("POST", "/payments/webhook/", event)
    check("First webhook is applied", status, 200)
    check("First webhook is not marked duplicate", 200 if first_event["duplicate"] is False else 500, 200)
    status, duplicate_event = request("POST", "/payments/webhook/", event)
    check("Repeated webhook is accepted", status, 200)
    check("Repeated webhook is marked duplicate", 200 if duplicate_event["duplicate"] is True else 500, 200)
    status, _ = request("POST", "/payments/webhook/", {**event, "status": "FAILED"})
    check("Webhook event ID cannot be reused with changed payload", status, 409)
    status, _ = request("POST", "/payments/webhook/", {
        "event_id": f"unknown-{uuid.uuid4().hex}", "payment_id": 999999999, "status": "SUCCESS",
    })
    check("Unknown webhook payment is rejected", status, 404)

    status, _ = request("POST", "/auth/login", {"email": email_a, "password": "definitely-wrong"})
    check("Wrong password is rejected", status, 401)

    print("\nRate-limit check: sending invalid logins until the API returns HTTP 429.")
    got_limited = False
    for _ in range(15):
        status, _ = request("POST", "/auth/login", {
            "email": f"missing-{uuid.uuid4().hex}@example.com", "password": "wrong-password",
        })
        if status == 429:
            got_limited = True
            break
        if status != 401:
            break
    check("Authentication rate limit returns HTTP 429", 429 if got_limited else status, 429)

    print(f"\nEdge-case results: {passed} passed, {failed} failed.")
    if failed:
        sys.exit(1)


def main():
    global API_BASE
    print("EVE Healthcare API - interactive terminal demo")
    API_BASE = ask_api_base()
    print("\nSign in to an existing account, or register if this is your first time.")
    account = authenticate_account()
    is_admin = account[2]["is_admin"]
    if is_admin:
        menu = [
            (3, "Admin catalogue tools", lambda: admin_catalog_demo(account)),
            (5, "Exit", None),
        ]
    else:
        menu = [
            (1, "Interactive booking and payment", lambda: normal_demo(account)),
            (2, "View/cancel my bookings", lambda: manage_my_bookings(account)),
            (3, "Run the edge-case tour", "edge_case_tour"),
            (4, "Exit", None),
        ]

    while True:
        print("\nWhat would you like to do?")
        for number, label, _ in menu:
            print(f"  {number}. {label}")
        valid_options = {number for number, _, _ in menu}
        default_option = str(menu[0][0])
        choice = ask("Choose an option", default_option)

        try:
            selected = int(choice)
        except ValueError:
            print(f"Choose one of these options: {', '.join(map(str, sorted(valid_options)))}.")
            continue
        if selected not in valid_options:
            print(f"Choose one of these options: {', '.join(map(str, sorted(valid_options)))}.")
            continue
        if selected == 5 or (not is_admin and selected == 4):
            print("Goodbye.")
            return
        action = next(item[2] for item in menu if item[0] == selected)
        if action == "edge_case_tour":
            print("\nThis tour creates demo users, bookings, and payments.")
            print("It also exercises the login rate limit; further login attempts from this IP may be limited for up to one minute.")
            if ask("Continue? (y/n)", "y").lower() in {"y", "yes"}:
                edge_case_tour(account)
            else:
                print("Cancelled.")
        else:
            action()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nDemo cancelled.")
        sys.exit(130)
    except RuntimeError as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        sys.exit(1)
