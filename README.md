# EVE Healthcare Diagnostic Booking API

A small backend service for finding diagnostic tests, booking an appointment, and simulating payment. It is built with FastAPI, SQLAlchemy, PostgreSQL, and Redis.

This project is an SDE intern assignment implementation. Centre names, tests, and prices are fictional examples for demonstration; they are not medical advice or real service listings.

## What the service does

- Patients can create an account, log in, browse diagnostic centres and their test prices, create bookings, pay with a simulated payment endpoint, view their bookings, and cancel eligible bookings.
- An administrator can add centres, add diagnostic tests, and offer tests at centres with a centre-specific price.
- The API prevents two active bookings for the same centre, test, and exact appointment time.
- A failed payment can be retried with a new idempotency key. A repeated payment request with the same key returns the original result.
- A simulated payment webhook can be replayed safely: the same event does not get applied twice.
- The interactive terminal demo walks through normal use and important failure cases.

## Assignment requirements and implementation

| Assignment area | What this project implements |
| --- | --- |
| Authentication | Patient signup, login, password hashing, JWT bearer tokens, and request validation. |
| Diagnostic centres and tests | Public catalogue endpoint, sample catalogue data, admin endpoints to add centres/tests and add or update centre-specific test prices. |
| Booking system | Authenticated booking with patient, centre, test, appointment time, price snapshot, and status. |
| Booking states | `PENDING`, `CONFIRMED`, `FAILED`, and `CANCELLED` are represented and constrained in the database. |
| Simulated payment | `POST /payments/` produces a simulated `SUCCESS` or `FAILED` result and updates the booking. No real payment provider is connected. |
| Payment webhook | `POST /payments/webhook/` records provider event IDs and handles duplicate delivery idempotently. |
| Edge cases | Invalid requests and IDs, unauthorized access, double booking, failed payments/retries, cancelled bookings, webhook replays, and rate limits are covered by the interactive tour and/or automated tests. |
| Submission files | This repository includes a README, requirements file, Dockerfile, Docker Compose configuration, application source, and tests. |

## My understanding and design decisions

The assignment asks for a small, understandable backend rather than a production diagnostic platform. I made these assumptions to keep the service testable while showing the important backend behavior:

1. **The catalogue is sample data.** Three fictional Gurgaon centres and their offers are seeded when the API starts. I did not use a Kaggle dataset because the assignment needs a small catalogue to demonstrate relationships and API behavior, not patient or operational data.
2. **An appointment is an exact timestamp.** There is no separate calendar or list of available time slots. The patient supplies a future, timezone-aware appointment time. For this assignment, one active booking can hold a centre/test/exact-time combination. A real service would need configurable capacity, opening hours, and availability rules.
3. **The booking keeps the price it was created with.** The booking amount is copied from the centre's offer at booking time. A later catalogue price change does not change an existing booking.
4. **Payment is simulated.** The API never charges a card. A request can simulate a failure; a failed booking may be retried with a new idempotency key or cancelled.
5. **Webhook delivery may repeat.** The event ID is stored as a unique key. Repeating the same event returns a duplicate response; reusing an event ID with a different payload is rejected.
6. **Admin permission is assigned by the server.** Choosing an admin menu or changing a request body cannot grant admin access. Docker Compose provisions one local demo admin account; normal signup creates a patient account.
7. **I prioritized the required backend behavior.** There is no web dashboard, real payment integration, appointment rescheduling, refund flow, or admin view of every patient's booking.

## Run with Docker Compose (recommended)

### Requirements

- Docker Desktop with Docker Compose on Windows, or Docker Engine with the Compose plugin on Linux/macOS.
- Python 3.12 or newer only if you want to run the terminal demo or automated tests on your host machine.

From the project folder, start the API, PostgreSQL, and Redis:

```cmd
docker compose up --build -d
```

Check service status and API health:

```cmd
docker compose ps
curl.exe http://localhost:8000/health
```

The health endpoint should return `{"status":"ok"}`. API documentation is available at <http://localhost:8000/docs> and <http://localhost:8000/redoc>.

### Local demo administrator

Docker Compose provisions this local-only account at API startup:

- Email: `admin@dig.com`
- Password: `admin`

The password is hashed before it is stored. The configured demo account is created or reset when the API starts. These weak, fixed credentials are only for a local assignment demo. Change them and use a strong JWT secret before any shared deployment.

### Stop the services

```cmd
docker compose down
```

This stops the containers and preserves the PostgreSQL volume. Do not add `-v` unless you intentionally want to delete the database and all saved bookings, users, payments, and catalogue changes.

Useful troubleshooting commands:

```cmd
docker compose logs -f api
docker compose logs -f db
docker compose logs -f redis
```

## Try the interactive terminal demo

Keep Docker Compose running, open a second Command Prompt in the project folder, then run:

```cmd
python .\scripts\terminal_demo.py
```

Press Enter at the API URL prompt to use `http://localhost:8000`. The first account prompts are email and hidden password. The CLI tries login first. If login fails, it explains that the account may be new or the password may be incorrect; you can retry or register that email by providing your name. After authentication, it reads the actual role from the server.

### Patient menu

Patients see:

1. **Interactive booking and payment** — choose a centre, an offered test, a future appointment time, then simulate payment success or failure. A failed payment can be retried.
2. **View/cancel my bookings** — list this account's bookings and cancel a pending or failed booking.
3. **Run the edge-case tour** — run the guided API checks.
4. **Exit**.

Appointment input uses local time as `YYYY-MM-DD HH:MM`, for example `2035-01-01 10:00`. The CLI adds the machine's local timezone before sending an ISO 8601 timestamp to the API.

### Admin menu

Admins see only:

3. **Admin catalogue tools** — list centres/offers; add a centre; create a test and offer it at a centre; or offer an existing test at a centre/update its price.
5. **Exit**.

Sign in using the local demo admin credentials above. Admin tools manage catalogue data, not appointment dates or patient bookings. The API has no booking reschedule or admin booking-management endpoint.

### Edge-case tour

The tour uses the signed-in patient as account A, then asks you to sign in to or create a second patient with a different email as account B. It needs two users to demonstrate that one patient cannot read or pay for another patient's booking. The tour prints a `[PASS]` or `[FAIL]` line for each check and exits with a failure status if a check fails.

The tour deliberately sends login attempts until the API returns HTTP 429 to demonstrate the authentication rate limit. The limit is shared by requests from the same IP and remains active for up to 60 seconds. If you exit and immediately start the CLI again, wait about one minute before logging in. The CLI explains the cooldown if it encounters this rate limit.

## Run the automated tests

The API tests use a temporary SQLite database configured by the test fixture. You do not need Docker running to execute them. In Windows Command Prompt:

```cmd
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
```

In PowerShell, activate the environment with:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest
```

The automated suite covers authentication, role checks, catalogue seed data, booking validation and ownership, double booking, payment success/failure and retries, webhook idempotency, and rate limiting. The interactive edge-case tour exercises these behaviors through the running HTTP API from the terminal.

## API reference

Base URL: `http://localhost:8000`. Open `/docs` for the interactive OpenAPI reference. Protected endpoints expect `Authorization: Bearer <access_token>` from `/auth/login`.

| Method | Path | Access | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | Public | Health check. |
| `POST` | `/auth/signup` | Public | Create a patient account. |
| `POST` | `/auth/login` | Public | Get a JWT access token. |
| `GET` | `/auth/me` | Signed in | Read the signed-in user's profile and server-assigned role. |
| `GET` | `/centres` | Public | List centres, tests, and centre-specific prices. |
| `POST` | `/centres` | Admin | Add a diagnostic centre. |
| `POST` | `/tests` | Admin | Add a diagnostic test. |
| `PUT` | `/centres/{centre_id}/tests` | Admin | Add a test offer or update its price at a centre. |
| `POST` | `/bookings` | Signed in | Create a future appointment. |
| `GET` | `/bookings` | Signed in | List the current user's bookings. |
| `GET` | `/bookings/{booking_id}` | Booking owner | Read a booking. |
| `POST` | `/bookings/{booking_id}/cancel` | Booking owner | Cancel a pending or failed booking. |
| `POST` | `/payments/` | Booking owner | Simulate payment. |
| `POST` | `/payments/webhook/` | Simulated provider | Apply a payment-status event idempotently. |

### Example request bodies

Create a patient account (`POST /auth/signup`):

```json
{"name":"Asha Rao","email":"asha@example.com","password":"correct-horse-8"}
```

Log in (`POST /auth/login`):

```json
{"email":"asha@example.com","password":"correct-horse-8"}
```

Use the returned access token as a bearer token for protected requests. First fetch `GET /centres`, then choose a centre ID and one of its offered test IDs to create a booking (`POST /bookings`):

```json
{"centre_id":1,"test_id":1,"appointment_at":"2035-01-01T10:00:00+05:30"}
```

Simulate payment (`POST /payments/`):

```json
{"booking_id":1,"idempotency_key":"checkout-attempt-1"}
```

To simulate a failed payment, set `simulate_failure` to `true`. Reuse of the same key returns the same payment. A retry after failure must use a new key:

```json
{"booking_id":1,"idempotency_key":"checkout-attempt-2"}
```

Simulate a provider webhook (`POST /payments/webhook/`):

```json
{"event_id":"provider-event-1","payment_id":1,"status":"SUCCESS"}
```

The webhook is intentionally a mock endpoint and does not validate provider signatures. A real integration must authenticate webhook requests.

## Data model and booking behavior

- **Users:** normalized, unique email; Argon2 password hash; active/admin flags.
- **Diagnostic centres and tests:** many-to-many relationship through `centre_tests`. The relationship stores a separate price for each centre/test pair.
- **Bookings:** refer to a patient, centre, test, timezone-aware appointment timestamp, amount, and status. The amount snapshots the listed price at creation.
- **Payments:** refer to a booking, store the amount/status, and have a unique `(booking_id, idempotency_key)` constraint.
- **Webhook events:** provider event ID is the primary key, so duplicate event IDs cannot create duplicate event records.

Normal state changes are:

```text
New booking -> PENDING -> payment succeeds -> CONFIRMED
                         -> payment fails    -> FAILED -> retry with new key -> CONFIRMED
                                                    \-> patient cancels -> CANCELLED
             -> patient cancels while PENDING -> CANCELLED
```

Only the booking owner can view, pay for, or cancel their booking. Only pending or failed bookings can be cancelled. A confirmed booking cannot be cancelled. A failed booking retains its appointment time while a payment retry is possible; cancellation releases it. The database enforces one non-cancelled booking for each centre, test, and exact timestamp, including when concurrent requests race.

## Seed catalogue

The catalogue is hand-authored in `app/seed.py` and seeded idempotently when the API starts:

| Centre | Example offers |
| --- | --- |
| EVE Central Diagnostics — Sector 29, Gurgaon | CBC ₹450; Lipid Profile ₹850; Thyroid Profile ₹700 |
| EVE Diagnostics — DLF Phase 3, Gurgaon | Vitamin D ₹1,200; Thyroid Profile ₹750; HbA1c ₹650 |
| EVE Health Labs — Sector 56, Gurgaon | CBC ₹500; Lipid Profile ₹900; HbA1c ₹600 |

The public catalogue endpoint also returns centres/tests added by an administrator.

## Optional assignment features

| Feature | Status | Notes |
| --- | --- | --- |
| Redis caching | Implemented | Centre catalogue cached for 60 seconds; successful catalogue mutations invalidate it. |
| Celery/background jobs | Not implemented | Not needed for the synchronous mock-payment scope. |
| Docker and Docker Compose | Implemented | API, PostgreSQL, and Redis services. |
| Swagger/OpenAPI | Implemented | FastAPI docs at `/docs` and `/redoc`. |
| Unit/integration tests | Implemented | Run with `python -m pytest`. |
| Structured logging | Not implemented | Redis fallback/failure messages use standard logging; there is no structured JSON logging setup. |
| Pagination | Not implemented | Current demo data and endpoints return complete result lists. |
| Rate limiting | Implemented | Per client IP: 10 auth, 30 payment, and 120 other API requests per 60-second window by default. HTTP 429 responses include `Retry-After`. |
| Webhook retry handling | Partially covered | Repeated delivery is idempotent, but there is no background retry worker or delivery-attempt queue. |

## Configuration

Docker Compose supplies local defaults. For running the API directly, copy `.env.example` to `.env` and set values for your local services. Main settings:

- `DATABASE_URL`: SQLAlchemy PostgreSQL URL.
- `REDIS_URL`: Redis URL; if Redis is unavailable, cache operations fall back safely and rate limits use process-local counters.
- `JWT_SECRET_KEY`: signing key for access tokens. Set a long, private value outside local development.
- `ADMIN_EMAIL` and `ADMIN_PASSWORD`: configured local administrator identity.
- `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_AUTH_REQUESTS`, `RATE_LIMIT_PAYMENT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`: rate-limit settings.

## Repository layout

```text
app/                    FastAPI application, database models, seed data, and services
scripts/terminal_demo.py Interactive patient/admin and edge-case terminal demo
tests/                  API integration tests and fixtures
Dockerfile              API container image
docker-compose.yml      API, PostgreSQL, and Redis local stack
requirements.txt        Python dependencies
pytest.ini              Pytest configuration
.env.example            Example local configuration
README.md               Setup, API, data-model, and design documentation
```

## Improvements with more time

- Add real slot capacity, opening hours, and appointment availability rules.
- Add booking rescheduling, cancellation/refund rules, and an admin booking view.
- Authenticate webhooks with provider signatures and add delivery-attempt tracking/retries.
- Add database migrations, pagination, structured logs, metrics, and production secret management.
- Add staff role/invitation workflows instead of local demo administrator credentials.
- Add Google Tag Manager (GTM) for privacy-conscious product analytics, excluding patient identifiers and health details.
