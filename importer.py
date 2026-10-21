"""Batch import with bounded retries and idempotent SQLite persistence."""

from collections.abc import Callable, Mapping, Sequence
import sqlite3
import time


Record = Mapping[str, str]
ApiRequest = Callable[[Sequence[Record]], None]


class TemporaryApiError(Exception):
    """A request failure that may succeed when retried."""


class RateLimitError(TemporaryApiError):
    """HTTP 429, optionally including the server's Retry-After value."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("the external API rate limit was exceeded")
        self.retry_after = retry_after


class DailyRequestLimitError(RuntimeError):
    """The importer cannot make another request within today's budget."""


def create_schema(connection: sqlite3.Connection) -> None:
    with connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                external_id TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
            """
        )


def import_records(
    records: Sequence[Record],
    api_request: ApiRequest,
    connection: sqlite3.Connection,
    *,
    daily_limit: int = 100,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Process and persist records in batches, returning requests consumed.

    One call represents one day's import budget. Every API attempt, including a
    failed attempt, consumes one request. Successful batches are committed
    independently so the function can be safely rerun after an interruption.
    """
    if daily_limit < 1:
        raise ValueError("daily_limit must be at least 1")
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if base_delay < 0:
        raise ValueError("base_delay cannot be negative")

    requests_used = 0

    for start in range(0, len(records), 25):
        batch = records[start : start + 25]

        for attempt in range(max_attempts):
            if requests_used == daily_limit:
                raise DailyRequestLimitError(
                    f"daily request limit of {daily_limit} reached"
                )

            requests_used += 1
            try:
                api_request(batch)
                break
            except TemporaryApiError as error:
                if attempt + 1 == max_attempts:
                    raise
                if requests_used == daily_limit:
                    raise DailyRequestLimitError(
                        f"daily request limit of {daily_limit} reached"
                    ) from error

                delay = base_delay * (2**attempt)
                if isinstance(error, RateLimitError) and error.retry_after is not None:
                    delay = max(0.0, error.retry_after)
                sleep(delay)

        with connection:
            connection.executemany(
                """
                INSERT INTO records (external_id, name)
                VALUES (:external_id, :name)
                ON CONFLICT(external_id) DO UPDATE SET name = excluded.name
                """,
                batch,
            )

    return requests_used
