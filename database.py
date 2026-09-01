import sqlite3
from contextlib import contextmanager
from datetime import datetime


DATABASE_FILE = "tickets.db"


@contextmanager
def get_connection():
    connection = sqlite3.connect(
        DATABASE_FILE
    )

    connection.row_factory = (
        sqlite3.Row
    )

    try:
        yield connection
        connection.commit()

    finally:
        connection.close()


def ensure_column(
    connection,
    table_name: str,
    column_name: str,
    column_definition: str,
):
    cursor = connection.execute(
        f"PRAGMA table_info({table_name})"
    )

    columns = {
        row["name"]
        for row in cursor.fetchall()
    }

    if column_name in columns:
        return

    connection.execute(
        f"""
        ALTER TABLE {table_name}
        ADD COLUMN {column_name} {column_definition}
        """
    )


def init_database():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pumble_message_id TEXT NOT NULL,
                support_account TEXT NOT NULL,
                pumble_channel_id TEXT NOT NULL,
                plaky_item_id TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pumble_message_id, support_account)
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS integration_state (
                support_account TEXT PRIMARY KEY,
                initialized INTEGER NOT NULL DEFAULT 0,
                initialized_at DATETIME
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_code TEXT UNIQUE NOT NULL,
                support_account TEXT NOT NULL,
                requester_id TEXT,
                requester_name TEXT,
                pumble_channel_id TEXT NOT NULL,
                pumble_message_id TEXT NOT NULL,
                plaky_item_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                requested_at TEXT NOT NULL,
                last_status TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(pumble_message_id, support_account)
            )
            """
        )

        ensure_column(
            connection=connection,
            table_name="tickets",
            column_name="last_status",
            column_definition="TEXT",
        )


def is_message_processed(
    message_id: str,
    support_account: str,
) -> bool:

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT 1
            FROM processed_messages
            WHERE pumble_message_id = ?
              AND support_account = ?
            LIMIT 1
            """,
            (
                message_id,
                support_account,
            ),
        )

        return (
            cursor.fetchone()
            is not None
        )


def mark_message_processed(
    message_id: str,
    support_account: str,
    channel_id: str,
    plaky_item_id: str | None = None,
):

    with get_connection() as connection:
        connection.execute(
            """
            INSERT OR IGNORE INTO processed_messages (
                pumble_message_id,
                support_account,
                pumble_channel_id,
                plaky_item_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                message_id,
                support_account,
                channel_id,
                plaky_item_id,
            ),
        )


def is_account_initialized(
    support_account: str,
) -> bool:

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT initialized
            FROM integration_state
            WHERE support_account = ?
            LIMIT 1
            """,
            (
                support_account,
            ),
        )

        row = cursor.fetchone()

        return bool(
            row
            and row["initialized"]
        )


def mark_account_initialized(
    support_account: str,
):

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO integration_state (
                support_account,
                initialized,
                initialized_at
            )
            VALUES (?, 1, CURRENT_TIMESTAMP)

            ON CONFLICT(support_account)
            DO UPDATE SET
                initialized = 1,
                initialized_at = CURRENT_TIMESTAMP
            """,
            (
                support_account,
            ),
        )


def generate_ticket_code(
    support_account: str,
    requested_at: str,
) -> str:

    prefix = {
        "ti": "TI",
        "assisthemis": "AST",
        "liderhub": "LDH",
    }.get(
        support_account,
        support_account.upper(),
    )

    try:
        date = datetime.fromisoformat(
            requested_at.replace(
                "Z",
                "+00:00",
            )
        )

        date_part = (
            date.strftime(
                "%Y%m%d"
            )
        )

    except Exception:
        date_part = (
            datetime.now().strftime(
                "%Y%m%d"
            )
        )

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT ticket_code
            FROM tickets
            WHERE support_account = ?
              AND ticket_code LIKE ?
            """,
            (
                support_account,
                f"{prefix}-{date_part}-%",
            ),
        )

        max_sequence = 0

        for row in cursor.fetchall():
            ticket_code = (
                row["ticket_code"]
            )

            try:
                sequence = int(
                    ticket_code.rsplit(
                        "-",
                        1,
                    )[1]
                )

                max_sequence = max(
                    max_sequence,
                    sequence,
                )

            except Exception:
                continue

    sequence = (
        max_sequence + 1
    )

    return (
        f"{prefix}-"
        f"{date_part}-"
        f"{sequence:04d}"
    )


def create_ticket(
    ticket_code: str,
    support_account: str,
    requester_id: str | None,
    requester_name: str | None,
    channel_id: str,
    message_id: str,
    plaky_item_id: str | None,
    title: str,
    description: str,
    requested_at: str,
    last_status: str | None = None,
):

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO tickets (
                ticket_code,
                support_account,
                requester_id,
                requester_name,
                pumble_channel_id,
                pumble_message_id,
                plaky_item_id,
                title,
                description,
                requested_at,
                last_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_code,
                support_account,
                requester_id,
                requester_name,
                channel_id,
                message_id,
                plaky_item_id,
                title,
                description,
                requested_at,
                last_status,
            ),
        )


def get_ticket_by_code(
    ticket_code: str,
):

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT *
            FROM tickets
            WHERE ticket_code = ?
            LIMIT 1
            """,
            (
                ticket_code,
            ),
        )

        return cursor.fetchone()


def get_ticket_by_plaky_item_id(
    plaky_item_id: str,
):

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT *
            FROM tickets
            WHERE plaky_item_id = ?
            LIMIT 1
            """,
            (
                str(
                    plaky_item_id
                ),
            ),
        )

        return cursor.fetchone()


def get_monitored_tickets():
    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT *
            FROM tickets
            WHERE plaky_item_id IS NOT NULL
              AND plaky_item_id != ''
            ORDER BY id ASC
            """
        )

        return cursor.fetchall()


def update_ticket_status(
    ticket_code: str,
    status: str,
):

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE tickets
            SET last_status = ?
            WHERE ticket_code = ?
            """,
            (
                status,
                ticket_code,
            ),
        )


def get_ticket_last_status(
    ticket_code: str,
) -> str | None:

    with get_connection() as connection:
        cursor = connection.execute(
            """
            SELECT last_status
            FROM tickets
            WHERE ticket_code = ?
            LIMIT 1
            """,
            (
                ticket_code,
            ),
        )

        row = cursor.fetchone()

        if not row:
            return None

        return row[
            "last_status"
        ]