import requests

from config import (
    PLAKY_API_KEY,
    PLAKY_BASE_URL,
    PLAKY_SPACE_ID,
)


class PlakyClient:

    def __init__(self):
        self.session = (
            requests.Session()
        )

        self.session.headers.update({
            "X-API-Key": PLAKY_API_KEY,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def create_item(
        self,
        board_id: int,
        group_id: int,
        title: str,
    ):
        url = (
            f"{PLAKY_BASE_URL}"
            f"/spaces/{PLAKY_SPACE_ID}"
            f"/boards/{board_id}"
            f"/items"
        )

        payload = {
            "title": title,
            "groupId": group_id,
        }

        response = self.session.post(
            url,
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    def update_field(
        self,
        board_id: int,
        item_id: int,
        field_key: str,
        value,
    ):
        url = (
            f"{PLAKY_BASE_URL}"
            f"/spaces/{PLAKY_SPACE_ID}"
            f"/boards/{board_id}"
            f"/items/{item_id}"
            f"/fields/{field_key}"
        )

        response = self.session.patch(
            url,
            json={
                "value": value,
            },
            timeout=30,
        )

        response.raise_for_status()

        if not response.content:
            return None

        return response.json()

    def set_description(
        self,
        board_id: int,
        item_id: int,
        description: str,
    ):
        return self.update_field(
            board_id=board_id,
            item_id=item_id,
            field_key="rich_text-1",
            value=description,
        )

    def set_date(
        self,
        board_id: int,
        item_id: int,
        requested_at: str,
    ):
        return self.update_field(
            board_id=board_id,
            item_id=item_id,
            field_key="date_time-1",
            value=requested_at,
        )

    def set_status(
        self,
        board_id: int,
        item_id: int,
        status: str,
    ):
        return self.update_field(
            board_id=board_id,
            item_id=item_id,
            field_key="status-1",
            value=status,
        )

    def set_tags(
        self,
        board_id: int,
        item_id: int,
        tags: list[str],
    ):
        return self.update_field(
            board_id=board_id,
            item_id=item_id,
            field_key="tag-1",
            value=tags,
        )

    def set_person(
        self,
        board_id: int,
        item_id: int,
        users=None,
        teams=None,
    ):
        value = {
            "users": users or [],
            "teams": teams or [],
        }

        return self.update_field(
            board_id=board_id,
            item_id=item_id,
            field_key="person-1",
            value=value,
        )

    def get_item(
        self,
        board_id: int,
        item_id: int,
    ):
        url = (
            f"{PLAKY_BASE_URL}"
            f"/spaces/{PLAKY_SPACE_ID}"
            f"/boards/{board_id}"
            f"/items/{item_id}"
        )

        response = self.session.get(
            url,
            params={
                "expand": "fields",
            },
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    def get_item_field_value(
        self,
        board_id: int,
        item_id: int,
        field_key: str,
    ):
        item = self.get_item(
            board_id=board_id,
            item_id=item_id,
        )

        return self._find_field_value(
            item,
            field_key,
        )

    def _find_field_value(
        self,
        value,
        field_key: str,
    ):
        if isinstance(
            value,
            dict,
        ):
            current_key = (
                value.get("key")
                or value.get("fieldKey")
                or value.get(
                    "itemFieldKey"
                )
            )

            if current_key == field_key:
                if "value" in value:
                    return value["value"]

                if "selectedValue" in value:
                    return value[
                        "selectedValue"
                    ]

                if "selectedValues" in value:
                    return value[
                        "selectedValues"
                    ]

            for child in value.values():
                result = (
                    self._find_field_value(
                        child,
                        field_key,
                    )
                )

                if result is not None:
                    return result

        elif isinstance(
            value,
            list,
        ):
            for child in value:
                result = (
                    self._find_field_value(
                        child,
                        field_key,
                    )
                )

                if result is not None:
                    return result

        return None

    def get_item_status(
        self,
        board_id: int,
        item_id: int,
    ):
        return self.get_item_field_value(
            board_id=board_id,
            item_id=item_id,
            field_key="status-1",
        )