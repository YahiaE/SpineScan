import json
import os
import random
import time
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from gevent import sleep
from locust import HttpUser, between, task
from locust.exception import StopUser


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_FILE = Path(
    os.getenv("SPINESCAN_LOAD_SESSIONS_FILE", REPOSITORY_ROOT / ".loadtest/sessions.json")
)
IMAGE_FILE = Path(
    os.getenv(
        "SPINESCAN_LOAD_IMAGE",
        REPOSITORY_ROOT / "tests/load/fixtures/scan.jpg",
    )
)
MAX_ENTRIES = max(1, int(os.getenv("SPINESCAN_LOAD_MAX_ENTRIES", "16")))
MAX_POLL_ATTEMPTS = max(1, int(os.getenv("SPINESCAN_LOAD_MAX_POLL_ATTEMPTS", "8")))
PRODUCTION_HOSTS = {"ye-spinescan-api.fly.dev"}


@lru_cache(maxsize=1)
def load_session_cookies():
    if not SESSIONS_FILE.is_file():
        raise RuntimeError(
            f"Session-cookie file not found: {SESSIONS_FILE}. "
            "See tests/load/README.md for setup."
        )

    try:
        cookies = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read load-test sessions: {error}") from error

    if not isinstance(cookies, list) or not cookies:
        raise RuntimeError("The session file must contain a non-empty JSON array.")
    if not all(isinstance(cookie, str) and cookie.strip() for cookie in cookies):
        raise RuntimeError("Each session must be a non-empty Flask session cookie.")
    return cookies


def extract_entries(result):
    if isinstance(result, dict):
        result = result.get("text", "")

    if not isinstance(result, str):
        return []

    entries = []
    for line in result.splitlines():
        line = line.strip()
        if " - " not in line or len(line.split()) > 12:
            continue
        artist, title = line.split(" - ", 1)
        if artist.strip() and title.strip():
            entries.append(
                {
                    "id": str(uuid.uuid4()),
                    "artist": artist.strip(),
                    "title": title.strip(),
                }
            )
        if len(entries) >= MAX_ENTRIES:
            break
    return entries


class ScanWorkflowUser(HttpUser):
    """Upload a fixture, OCR it, validate results, then clean up the capture."""

    wait_time = between(15, 30)

    def on_start(self):
        if os.getenv("SPINESCAN_LOAD_TEST_ENABLE") != "1":
            raise StopUser(
                "Set SPINESCAN_LOAD_TEST_ENABLE=1 to explicitly enable API traffic."
            )

        host = urlsplit(self.host or "").hostname
        if host in PRODUCTION_HOSTS and os.getenv(
            "SPINESCAN_LOAD_TEST_ALLOW_PRODUCTION"
        ) != "1":
            raise StopUser(
                "Production load tests are blocked unless "
                "SPINESCAN_LOAD_TEST_ALLOW_PRODUCTION=1 is set."
            )

        if not IMAGE_FILE.is_file():
            raise StopUser(
                f"Load-test image not found: {IMAGE_FILE}. "
                "Provide SPINESCAN_LOAD_IMAGE; see tests/load/README.md."
            )

        session_cookie = random.choice(load_session_cookies()).strip()
        if "=" in session_cookie:
            cookie_name, cookie_value = session_cookie.split("=", 1)
        else:
            cookie_name, cookie_value = "session", session_cookie
        self.client.cookies.set(cookie_name, cookie_value)

    def request_json(
        self,
        method,
        path,
        name,
        expected_status=200,
        **request_kwargs,
    ):
        with self.client.request(
            method,
            path,
            name=name,
            catch_response=True,
            **request_kwargs,
        ) as response:
            expected_statuses = (
                expected_status
                if isinstance(expected_status, tuple)
                else (expected_status,)
            )
            if response.status_code not in expected_statuses:
                response.failure(
                    f"Expected HTTP {expected_statuses}; got {response.status_code}"
                )
                raise StopUser()
            try:
                payload = response.json()
            except ValueError:
                response.failure("Response was not valid JSON")
                raise StopUser()
            response.success()
            return payload

    def validate_entries(self, entries):
        payload = self.request_json(
            "POST",
            "/api/discogs/validate",
            "POST /api/discogs/validate",
            json={"entries": entries},
        )
        validations = {item["id"]: item for item in payload.get("validations", [])}

        for attempt in range(MAX_POLL_ATTEMPTS):
            pending = [
                entry
                for entry in entries
                if validations.get(entry["id"], {}).get("status") == "pending"
            ]
            if not pending:
                return

            sleep(min(1.5 * (1.5**attempt), 10))
            status_payload = self.request_json(
                "POST",
                "/api/discogs/validation-status",
                "POST /api/discogs/validation-status",
                json={"entries": pending},
            )
            validations.update(
                {
                    item["id"]: item
                    for item in status_payload.get("validations", [])
                }
            )

            retry_ids = set(status_payload.get("retry_ids", []))
            if retry_ids:
                retry_entries = [
                    entry for entry in pending if entry["id"] in retry_ids
                ]
                retry_payload = self.request_json(
                    "POST",
                    "/api/discogs/validate",
                    "POST /api/discogs/validate (retry)",
                    json={"entries": retry_entries},
                )
                validations.update(
                    {
                        item["id"]: item
                        for item in retry_payload.get("validations", [])
                    }
                )

        if any(
            validations.get(entry["id"], {}).get("status") == "pending"
            for entry in entries
        ):
            raise RuntimeError("Validation remained pending after the poll limit.")

    @task
    def scan_and_validate(self):
        capture_path = None
        try:
            with IMAGE_FILE.open("rb") as image_file:
                upload_payload = self.request_json(
                    "POST",
                    "/api/data/upload",
                    "POST /api/data/upload",
                    files={
                        "file": (
                            IMAGE_FILE.name,
                            image_file,
                            "image/jpeg",
                        )
                    },
                )
                capture_path = upload_payload.get("path")
                if not capture_path:
                    raise RuntimeError("Upload response did not include a capture path")

            process_payload = self.request_json(
                "GET",
                "/api/process/latest",
                "GET /api/process/latest (OCR)",
                params={"path": capture_path},
            )
            entries = extract_entries(process_payload.get("result"))
            if not entries:
                raise RuntimeError("OCR produced no Artist - Album entries")

            self.validate_entries(entries)
        except StopUser:
            raise
        except Exception as error:
            self.environment.events.request.fire(
                request_type="WORKFLOW",
                name="scan-to-validation",
                response_time=0,
                response_length=0,
                exception=error,
                context={},
            )
            raise
        finally:
            if capture_path:
                try:
                    self.request_json(
                        "POST",
                        "/api/data/capture/finalize",
                        "POST /api/data/capture/finalize",
                        expected_status=(200, 202),
                        json={"path": capture_path},
                    )
                except StopUser:
                    pass