# School Basics Python Technical Assessment

## Overview

This project is a small, framework-free Python implementation of the School
Basics import exercise. It demonstrates how to:

- process records in batches of no more than 25;
- enforce a maximum of 100 external request attempts per import run;
- retry temporary failures and HTTP 429 responses without retrying forever;
- persist records with an idempotent SQL upsert; and
- test the behavior without making network requests or connecting to an
  external database.

The solution deliberately stays small. It uses an injected function to
represent the external API and SQLite to demonstrate the persistence SQL.

## Project files

```text
importer.py       Import, retry, request-limit, and persistence logic
test_importer.py  PyTest tests using mocked API calls and in-memory SQLite
README.md         Setup, behavior, assumptions, and tradeoffs
```

## How the importer works

The main function is `import_records` in `importer.py`. It receives:

1. a sequence of records;
2. a callable representing one external API request; and
3. a SQLite connection used by the persistence example.

Each record must contain:

```python
{"external_id": "SB-1001", "name": "Notebook"}
```

The function processes the input in this order:

1. Split the records into batches of at most 25.
2. Check that another request is available within the request budget.
3. Call the injected API function for the batch.
4. Retry only `TemporaryApiError` and `RateLimitError` failures.
5. Upsert the batch after the external operation succeeds.
6. Commit each successful batch independently.
7. Return the total number of request attempts consumed.

Every attempt counts toward the request limit, including failed attempts. With
no failures, 100 requests of 25 records allow up to 2,500 records in one run.

## Retry behavior

The default configuration allows three total attempts per batch: the original
attempt and up to two retries.

For a temporary failure, the fallback delay uses exponential backoff:

```text
after attempt 1: 1 second
after attempt 2: 2 seconds
```

For HTTP 429, `RateLimitError` may contain a `retry_after` value. That value
takes precedence over exponential backoff. A negative value is treated as
zero. The importer raises the last temporary error after all attempts are
used. Other exception types are treated as permanent and are not retried.

The sleep function is injectable. Tests pass a mock sleep function, so the
suite checks the intended delays without actually waiting.

## Duplicate prevention and persistence

The database demonstration creates this table:

```sql
CREATE TABLE IF NOT EXISTS records (
    external_id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
```

Records are written with:

```sql
INSERT INTO records (external_id, name)
VALUES (:external_id, :name)
ON CONFLICT(external_id) DO UPDATE SET name = excluded.name;
```

Because `external_id` is the primary key, the database cannot contain two rows
with the same external ID. Reimporting a record updates its name instead of
creating a duplicate. If the input contains the same ID more than once, the
last processed name is retained.

Each successful batch uses its own transaction. If a later batch fails,
earlier batches remain committed and the import can be safely rerun because
the upsert is idempotent.

## Running the tests

Python 3.10 or newer is required. From this directory, run:

```powershell
python -m pip install pytest
python -m pytest -q
```

Expected result:

```text
4 passed
```

The tests cover:

- splitting records into 25-record batches;
- updating repeated external IDs without duplicate database rows;
- retrying a temporary failure with exponential backoff;
- honoring `Retry-After` for HTTP 429;
- counting failed attempts toward the request limit; and
- avoiding database writes when a batch never succeeds.

All database tests use SQLite's in-memory mode, and all external calls are
mocked. The test suite does not require network access or create a database
file.

## Assumptions and tradeoffs

- One call to `import_records` represents one daily import run. The request
  count is not persisted by calendar date or shared between processes.
- Input records are assumed to contain valid `external_id` and `name` keys, as
  stated in the assessment. Custom input validation was left out to keep the
  example focused.
- Duplicate input records can still be included in an external batch. The
  database primary key and upsert prevent duplicate stored rows.
- Backoff has no random jitter, and a very large `Retry-After` value is not
  capped.
- Committing per batch allows safe progress and resumption, but the entire
  import is not one atomic transaction.
- SQLite and `create_schema` are included only to make the SQL behavior
  executable. A production service would use its normal database and migration
  system.

## Production improvements

Before deployment, I would add:

- a shared, date-scoped request counter;
- a durable import checkpoint for interrupted runs;
- structured logging and metrics for attempts, retries, failures, and imported
  records;
- configuration and secret management;
- input validation;
- jitter and a maximum delay for backoff; and
- integration with the real API client and production database layer.

## Tool disclosure

I used an AI coding assistant to review the assessment, discuss the design, and
help draft and test the implementation. I reviewed the resulting code and can
explain its behavior and tradeoffs.
