import requests

from config import PUMBLE_BASE_URL


class PumbleClient:

    def __init__(
        self,
        api_key: str,
    ):
        self.session = (
            requests.Session()
        )

        self.session.headers.update({
            "ApiKey": api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    def _get(
        self,
        path: str,
        params=None,
    ):
        response = self.session.get(
            f"{PUMBLE_BASE_URL}{path}",
            params=params,
            timeout=30,
        )

        response.raise_for_status()

        return response.json()

    def get_my_info(self):
        return self._get(
            "/myInfo"
        )

    def list_channels(self):
        response = self._get(
            "/listChannels"
        )

        if not isinstance(
            response,
            list,
        ):
            raise ValueError(
                "Formato inesperado em "
                f"/listChannels: {response}"
            )

        channels = []

        for item in response:
            channel = item.get(
                "channel"
            )

            if not isinstance(
                channel,
                dict,
            ):
                continue

            channel["users"] = (
                item.get(
                    "users",
                    [],
                )
            )

            channels.append(
                channel
            )

        return channels

    def list_messages(
        self,
        channel_id: str,
        limit: int = 50,
    ):
        response = self._get(
            "/listMessages",
            params={
                "channelId": channel_id,
                "limit": limit,
            },
        )

        if isinstance(
            response,
            list,
        ):
            return response

        if isinstance(
            response,
            dict,
        ):
            for key in (
                "messages",
                "data",
            ):
                value = response.get(
                    key
                )

                if isinstance(
                    value,
                    list,
                ):
                    return value

        raise ValueError(
            "Formato inesperado em "
            f"/listMessages: {response}"
        )

    def list_users(self):
        response = self._get(
            "/listUsers"
        )

        if isinstance(
            response,
            list,
        ):
            return response

        if isinstance(
            response,
            dict,
        ):
            for key in (
                "users",
                "data",
            ):
                value = response.get(
                    key
                )

                if isinstance(
                    value,
                    list,
                ):
                    return value

        raise ValueError(
            "Formato inesperado em "
            f"/listUsers: {response}"
        )

    def send_message(
        self,
        channel_id: str,
        text: str,
        as_bot: bool = False,
    ):
        if not channel_id:
            raise ValueError(
                "channel_id é obrigatório"
            )

        if (
            not text
            or not text.strip()
        ):
            raise ValueError(
                "text é obrigatório"
            )

        payload = {
            "channelId": channel_id,
            "text": text.strip(),
            "asBot": as_bot,
        }

        response = self.session.post(
            f"{PUMBLE_BASE_URL}/sendMessage",
            json=payload,
            timeout=30,
        )

        response.raise_for_status()

        if not response.content:
            return None

        try:
            return response.json()

        except ValueError:
            return {
                "status_code": (
                    response.status_code
                ),
                "text": (
                    response.text
                ),
            }