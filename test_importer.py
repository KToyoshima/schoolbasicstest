import sqlite3
from unittest.mock import Mock

import pytest

from importer import (
    DailyRequestLimitError,
    RateLimitError,
    TemporaryApiError,
    create_schema,
    import_records,
)


SAMPLE_RECORDS = [
    {"external_id": "SB-1001", "name": "Notebook"},
    {"external_id": "SB-1002", "name": "Pencil Case"},
    {"external_id": "SB-1003", "name": "Backpack"},
    {"external_id": "SB-1004", "name": "Folder"},
]


@pytest.fixture
def connection():
    database = sqlite3.connect(":memory:")
    create_schema(database)
    yield database
    database.close()


def test_imports_in_batches_and_upserts_duplicates(connection):
    records = [
        {"external_id": f"SB-{number}", "name": f"Item {number}"}
        for number in range(26)
    ]
    records.append({"external_id": "SB-0", "name": "Updated item"})
    api_request = Mock()

    requests_used = import_records(records, api_request, connection)

    assert requests_used == 2
    assert [len(call.args[0]) for call in api_request.call_args_list] == [25, 2]
    assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 26
    assert connection.execute(
        "SELECT name FROM records WHERE external_id = 'SB-0'"
    ).fetchone()[0] == "Updated item"


def test_retries_temporary_failure_with_exponential_backoff(connection):
    api_request = Mock(side_effect=[TemporaryApiError(), None])
    sleep = Mock()

    requests_used = import_records(
        SAMPLE_RECORDS, api_request, connection, sleep=sleep
    )

    assert requests_used == 2
    assert api_request.call_count == 2
    sleep.assert_called_once_with(1.0)


def test_429_uses_retry_after(connection):
    api_request = Mock(side_effect=[RateLimitError(retry_after=7), None])
    sleep = Mock()

    import_records(SAMPLE_RECORDS, api_request, connection, sleep=sleep)

    sleep.assert_called_once_with(7)


def test_daily_limit_counts_failed_attempts(connection):
    api_request = Mock(side_effect=TemporaryApiError())

    with pytest.raises(DailyRequestLimitError):
        import_records(
            SAMPLE_RECORDS,
            api_request,
            connection,
            daily_limit=2,
            sleep=Mock(),
        )

    assert api_request.call_count == 2
    assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
