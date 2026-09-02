import os

from dotenv import load_dotenv


load_dotenv()


def parse_user_ids(
    value: str | None,
) -> list[str]:
    if not value:
        return []

    return [
        user_id.strip()
        for user_id in value.split(",")
        if user_id.strip()
    ]


PUMBLE_BASE_URL = (
    "https://pumble-api-keys.addons.marketplace.cake.com"
)

PLAKY_BASE_URL = (
    "https://api.plaky.com/v1/public"
)

POLL_INTERVAL_SECONDS = int(
    os.getenv(
        "POLL_INTERVAL_SECONDS",
        "30",
    )
)

PLAKY_API_KEY = os.environ[
    "PLAKY_API_KEY"
]

PLAKY_SPACE_ID = int(
    os.environ[
        "PLAKY_SPACE_ID"
    ]
)


SUPPORT_ACCOUNTS = [
    {
        "key": "ti",
        "name": "Suporte TI",
        "pumble_api_key": os.environ[
            "PUMBLE_TI_API_KEY"
        ],
        "plaky_board_id": int(
            os.environ[
                "PLAKY_TI_BOARD_ID"
            ]
        ),
        "plaky_group_id": int(
            os.environ[
                "PLAKY_TI_GROUP_ID"
            ]
        ),
        "notify_user_ids": parse_user_ids(
            os.getenv(
                "PUMBLE_TI_NOTIFY_USER_IDS"
            )
        ),
    },
    {
        "key": "assisthemis",
        "name": "Suporte Assisthemis",
        "pumble_api_key": os.environ[
            "PUMBLE_ASSISTHEMIS_API_KEY"
        ],
        "plaky_board_id": int(
            os.environ[
                "PLAKY_ASSISTHEMIS_BOARD_ID"
            ]
        ),
        "plaky_group_id": int(
            os.environ[
                "PLAKY_ASSISTHEMIS_GROUP_ID"
            ]
        ),
        "notify_user_ids": parse_user_ids(
            os.getenv(
                "PUMBLE_ASSISTHEMIS_NOTIFY_USER_IDS"
            )
        ),
    },
    {
        "key": "liderhub",
        "name": "Suporte LiderHub",
        "pumble_api_key": os.environ[
            "PUMBLE_LIDERHUB_API_KEY"
        ],
        "plaky_board_id": int(
            os.environ[
                "PLAKY_LIDERHUB_BOARD_ID"
            ]
        ),
        "plaky_group_id": int(
            os.environ[
                "PLAKY_LIDERHUB_GROUP_ID"
            ]
        ),
        "notify_user_ids": parse_user_ids(
            os.getenv(
                "PUMBLE_LIDERHUB_NOTIFY_USER_IDS"
            )
        ),
    },
]