import os
from dotenv import load_dotenv


load_dotenv()


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
    },
]