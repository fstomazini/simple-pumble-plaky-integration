import logging
import time

from config import (
    POLL_INTERVAL_SECONDS,
    SUPPORT_ACCOUNTS,
)
from database import (
    create_ticket,
    generate_ticket_code,
    get_monitored_tickets,
    init_database,
    is_account_initialized,
    is_message_processed,
    mark_account_initialized,
    mark_message_processed,
    update_ticket_status,
)
from plaky import PlakyClient
from pumble import PumbleClient


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(message)s"
    ),
)

logger = logging.getLogger(__name__)

AUTO_REPLY_COOLDOWN_SECONDS = 10 * 60

last_auto_reply = {}

PLAKY_STATUS_NAMES = {
    "0": "Backlog",
    "1": "To do",
    "2": "In progress",
    "4": "Blocked",
    "3": "Done",
}


# ============================================================
# TEMPLATES
# ============================================================


def get_ticket_template_message(
    support_account: str,
) -> str:

    if support_account == "ti":
        return """Olá! 👋

Para abrir um novo chamado de TI, envie sua solicitação em uma única mensagem usando este modelo:

#NOVO-TICKET

Problema:
Local / equipamento:
Detalhes:

Exemplo:

#NOVO-TICKET

Problema: Mouse não está funcionando
Local / equipamento: Computador da recepção
Detalhes: O mouse acende, mas não movimenta o cursor.

Assim que a mensagem for enviada nesse formato, o chamado será registrado automaticamente."""

    if support_account == "assisthemis":
        return """Olá! 👋

Para registrar um problema no Assisthemis, envie sua solicitação em uma única mensagem usando este modelo:

#NOVO-TICKET

Problema:
O que estava fazendo:
O que aconteceu:
O que deveria acontecer:
Cliente / processo:

Exemplo:

#NOVO-TICKET

Problema: Não consigo salvar um novo cliente
O que estava fazendo: Realizando o cadastro de cliente
O que aconteceu: Ao clicar em Salvar, a tela fica carregando
O que deveria acontecer: O cadastro deveria ser concluído
Cliente / processo: João da Silva

Assim que a mensagem for enviada nesse formato, o chamado será registrado automaticamente."""

    if support_account == "liderhub":
        return """Para registrar um problema no LiderHub, envie sua solicitação em uma única mensagem usando este modelo:

#NOVO-TICKET

Problema:

O que estava fazendo:

O que aconteceu:

O que deveria acontecer:

Cliente / telefone:

Conexão:

workspace:

Exemplo:

#NOVO-TICKET

Problema: Não consigo enviar mensagem para o cliente Joao

O que estava fazendo: Realizando uma operação no LiderHub

O que aconteceu: Ao confirmar, o sistema não conclui a ação

O que deveria acontecer: A operação deveria ser concluída normalmente

Cliente / telefone: Cliente João da Silva

Conexão: +55 51 9xxxx-xxxx

workspace: Bancario

Assim que a mensagem for enviada nesse formato, o chamado será registrado automaticamente."""

    return """Para abrir um chamado, envie sua solicitação utilizando o marcador:

#NOVO-TICKET"""


def get_ticket_created_message(
    support_account: str,
    ticket_code: str,
) -> str:

    if support_account == "ti":
        return (
            f"✅ Chamado {ticket_code} criado com sucesso.\n\n"
            "Sua solicitação foi registrada no Suporte TI "
            "e será analisada conforme a fila de atendimento."
        )

    if support_account == "assisthemis":
        return (
            f"✅ Chamado {ticket_code} criado com sucesso.\n\n"
            "O problema foi registrado no Suporte Assisthemis "
            "e será analisado pela equipe responsável."
        )

    if support_account == "liderhub":
        return (
            f"✅ Chamado {ticket_code} criado com sucesso.\n\n"
            "O problema foi registrado no Suporte LiderHub "
            "e será analisado pela equipe responsável."
        )

    return (
        f"✅ Chamado {ticket_code} criado com sucesso."
    )


def get_status_changed_message(
    ticket_code: str,
    status: str,
) -> str | None:

    status = str(status)

    if status == "1":
        return (
            f"📋 O chamado {ticket_code} "
            "entrou na fila de atendimento."
        )

    if status == "2":
        return (
            f"🔄 O chamado {ticket_code} "
            "está em atendimento."
        )

    if status == "4":
        return (
            f"⏸️ O chamado {ticket_code} "
            "está temporariamente bloqueado.\n\n"
            "Caso seja necessária alguma informação adicional, "
            "o suporte entrará em contato."
        )

    if status == "3":
        return (
            f"✅ O chamado {ticket_code} foi concluído."
        )

    return None


# ============================================================
# PARSE DE MENSAGENS
# ============================================================


def extract_message_text(
    message: dict,
) -> str:

    text = message.get("text")

    if (
        isinstance(text, str)
        and text.strip()
    ):
        return text.strip()

    texts = []

    def walk(value):

        if isinstance(value, dict):

            if value.get("type") == "text":
                block_text = value.get("text")

                if isinstance(
                    block_text,
                    str,
                ):
                    texts.append(
                        block_text
                    )

            for child in value.values():
                walk(child)

        elif isinstance(value, list):

            for child in value:
                walk(child)

    walk(
        message.get(
            "blocks",
            [],
        )
    )

    return " ".join(texts).strip()


def normalize_text(
    text: str,
) -> str:
    return (
        text
        .lower()
        .strip()
    )


def extract_template_field(
    text: str,
    field_name: str,
) -> str | None:

    if not text:
        return None

    target = (
        field_name
        .lower()
        .strip()
    )

    for line in text.splitlines():

        line = line.strip()

        if (
            not line
            or ":" not in line
        ):
            continue

        key, value = line.split(
            ":",
            1,
        )

        if (
            key.lower().strip()
            == target
        ):
            value = value.strip()

            if value:
                return value

    return None


def has_template_field(
    text: str,
    field_name: str,
) -> bool:

    if not text:
        return False

    target = (
        field_name
        .lower()
        .strip()
    )

    for line in text.splitlines():

        line = line.strip()

        if ":" not in line:
            continue

        key, _ = line.split(
            ":",
            1,
        )

        if (
            key.lower().strip()
            == target
        ):
            return True

    return False


def is_ticket_template(
    text: str,
    support_account: str,
) -> bool:

    if not text:
        return False

    if (
        "#novo-ticket"
        not in normalize_text(text)
    ):
        return False

    if support_account == "ti":

        required_fields = [
            "Problema",
            "Local / equipamento",
            "Detalhes",
        ]

    elif support_account == "assisthemis":

        required_fields = [
            "Problema",
            "O que estava fazendo",
            "O que aconteceu",
            "O que deveria acontecer",
            "Cliente / processo",
        ]

    elif support_account == "liderhub":

        required_fields = [
            "Problema",
            "O que estava fazendo",
            "O que aconteceu",
            "O que deveria acontecer",
            "Cliente / telefone",
            "Conexão",
            "workspace",
        ]

    else:
        return False

    return all(
        has_template_field(
            text=text,
            field_name=field,
        )
        for field in required_fields
    )


def build_ticket_title(
    message: dict,
) -> str:

    text = extract_message_text(
        message
    )

    problem = extract_template_field(
        text=text,
        field_name="Problema",
    )

    title = (
        problem
        or "Solicitação sem descrição do problema"
    )

    if len(title) <= 120:
        return title

    return (
        title[:117]
        + "..."
    )


def build_plaky_description(
    requester_name: str | None,
    text: str,
) -> str:

    name = (
        requester_name
        or "Não identificado"
    )

    lines = []

    for line in text.splitlines():

        if (
            line.strip().lower()
            == "#novo-ticket"
        ):
            continue

        lines.append(line)

    cleaned_text = (
        "\n".join(lines).strip()
    )

    return (
        f"Solicitante: {name}\n\n"
        f"{cleaned_text}"
    )


# ============================================================
# RESPOSTAS
# ============================================================


def can_send_auto_reply(
    support_account: str,
    channel_id: str,
) -> bool:

    key = (
        support_account,
        channel_id,
    )

    last_sent = (
        last_auto_reply.get(key)
    )

    if last_sent is None:
        return True

    return (
        time.time() - last_sent
        >= AUTO_REPLY_COOLDOWN_SECONDS
    )


def register_auto_reply(
    support_account: str,
    channel_id: str,
):

    last_auto_reply[
        (
            support_account,
            channel_id,
        )
    ] = time.time()


def send_ticket_instructions(
    account: dict,
    pumble: PumbleClient,
    channel_id: str,
):

    if not can_send_auto_reply(
        support_account=account["key"],
        channel_id=channel_id,
    ):
        return

    pumble.send_message(
        channel_id=channel_id,
        text=get_ticket_template_message(
            account["key"]
        ),
        as_bot=False,
    )

    register_auto_reply(
        support_account=account["key"],
        channel_id=channel_id,
    )


def send_ticket_created_confirmation(
    account: dict,
    pumble: PumbleClient,
    channel_id: str,
    ticket_code: str,
):

    pumble.send_message(
        channel_id=channel_id,
        text=get_ticket_created_message(
            support_account=account["key"],
            ticket_code=ticket_code,
        ),
        as_bot=False,
    )


# ============================================================
# PUMBLE
# ============================================================


def get_direct_channels(
    pumble: PumbleClient,
):

    channels = (
        pumble.list_channels()
    )

    return [
        channel
        for channel in channels
        if (
            channel.get("channelType")
            == "DIRECT"
            and not channel.get(
                "isAddonBot",
                False,
            )
        )
    ]


def build_users_index(
    pumble: PumbleClient,
) -> dict:

    return {
        user["id"]: user
        for user in pumble.list_users()
        if (
            isinstance(user, dict)
            and user.get("id")
        )
    }


def resolve_requester(
    message: dict,
    users_by_id: dict,
):

    requester_id = (
        message.get("author")
    )

    requester = (
        users_by_id.get(
            requester_id
        )
    )

    if requester:

        requester_name = (
            requester.get("name")
            or requester.get("email")
            or requester_id
        )

    else:
        requester_name = (
            requester_id
        )

    return (
        requester_id,
        requester_name,
    )


# ============================================================
# NOTIFICAÇÃO DA EQUIPE
# ============================================================


def find_direct_channel_for_user(
    channels: list[dict],
    support_user_id: str,
    target_user_id: str,
) -> str | None:

    support_user_id = str(
        support_user_id
    )

    target_user_id = str(
        target_user_id
    )

    for channel in channels:

        if (
            channel.get("channelType")
            != "DIRECT"
        ):
            continue

        if channel.get(
            "isAddonBot",
            False,
        ):
            continue

        users = {
            str(user_id)
            for user_id
            in channel.get(
                "users",
                [],
            )
        }

        if (
            support_user_id in users
            and target_user_id in users
        ):
            return channel.get("id")

    return None


def notify_support_team(
    account: dict,
    pumble: PumbleClient,
    channels: list[dict],
    support_user_id: str,
    requester_id: str | None,
    requester_name: str | None,
    ticket_code: str,
    title: str,
):

    notify_user_ids = (
        account.get(
            "notify_user_ids",
            [],
        )
    )

    if not notify_user_ids:
        return

    display_name = (
        requester_name
        or requester_id
        or "Não identificado"
    )

    notification = (
        f"🆕 Novo chamado {ticket_code}\n\n"
        f"Fila: {account['name']}\n"
        f"Solicitante: {display_name}\n"
        f"Problema: {title}\n\n"
        "Um novo chamado foi adicionado "
        "à fila de atendimento."
    )

    for target_user_id in notify_user_ids:

        target_user_id = str(
            target_user_id
        )

        # Não envia uma segunda mensagem
        # caso o solicitante também seja
        # responsável pelo suporte.
        if (
            requester_id
            and target_user_id
            == str(requester_id)
        ):
            continue

        channel_id = (
            find_direct_channel_for_user(
                channels=channels,
                support_user_id=(
                    support_user_id
                ),
                target_user_id=(
                    target_user_id
                ),
            )
        )

        if not channel_id:

            logger.warning(
                "[%s] DM não encontrada "
                "para responsável %s.",
                account["name"],
                target_user_id,
            )

            continue

        try:

            pumble.send_message(
                channel_id=channel_id,
                text=notification,
                as_bot=False,
            )

            logger.info(
                "[%s] Responsável %s "
                "notificado sobre %s.",
                account["name"],
                target_user_id,
                ticket_code,
            )

        except Exception:

            logger.exception(
                "[%s] Erro ao notificar "
                "responsável %s sobre %s.",
                account["name"],
                target_user_id,
                ticket_code,
            )


# ============================================================
# PLAKY
# ============================================================


def extract_plaky_item_id(
    response: dict,
):

    if not isinstance(
        response,
        dict,
    ):
        return None

    item_id = response.get("id")

    if item_id is not None:
        return str(item_id)

    data = response.get("data")

    if isinstance(data, dict):

        item_id = data.get("id")

        if item_id is not None:
            return str(item_id)

    return None


def get_support_account(
    support_account: str,
):

    for account in SUPPORT_ACCOUNTS:

        if (
            account["key"]
            == support_account
        ):
            return account

    return None


# ============================================================
# BOOTSTRAP
# ============================================================


def bootstrap_account(
    account: dict,
    pumble: PumbleClient,
    support_user_id: str,
):

    logger.info(
        "[%s] Primeira execução. "
        "Registrando mensagens existentes "
        "sem criar tickets.",
        account["name"],
    )

    channels = (
        get_direct_channels(
            pumble
        )
    )

    marked_count = 0

    for channel in channels:

        channel_id = (
            channel.get("id")
        )

        if not channel_id:
            continue

        try:

            messages = (
                pumble.list_messages(
                    channel_id=channel_id,
                    limit=50,
                )
            )

        except Exception:

            logger.exception(
                "[%s] Erro lendo mensagens "
                "durante bootstrap da DM %s",
                account["name"],
                channel_id,
            )

            continue

        for message in messages:

            message_id = (
                message.get("id")
            )

            author_id = (
                message.get("author")
            )

            if not message_id:
                continue

            if (
                str(author_id)
                == str(support_user_id)
            ):
                continue

            mark_message_processed(
                message_id=message_id,
                support_account=account[
                    "key"
                ],
                channel_id=channel_id,
                plaky_item_id=None,
            )

            marked_count += 1

    mark_account_initialized(
        account["key"]
    )

    logger.info(
        "[%s] Bootstrap concluído. "
        "%s mensagens antigas registradas.",
        account["name"],
        marked_count,
    )


# ============================================================
# NOVOS TICKETS
# ============================================================


def process_account(
    account: dict,
    plaky: PlakyClient,
):

    pumble = PumbleClient(
        account["pumble_api_key"]
    )

    my_info = (
        pumble.get_my_info()
    )

    support_user_id = (
        my_info.get("id")
    )

    if not support_user_id:

        raise RuntimeError(
            "Não foi possível identificar "
            f"a conta {account['name']}"
        )

    if not is_account_initialized(
        account["key"]
    ):

        bootstrap_account(
            account=account,
            pumble=pumble,
            support_user_id=(
                support_user_id
            ),
        )

        return

    users_by_id = (
        build_users_index(
            pumble
        )
    )

    channels = (
        get_direct_channels(
            pumble
        )
    )

    logger.info(
        "[%s] %s DMs humanas encontradas.",
        account["name"],
        len(channels),
    )

    for channel in channels:

        channel_id = (
            channel.get("id")
        )

        if not channel_id:
            continue

        try:

            messages = (
                pumble.list_messages(
                    channel_id=channel_id,
                    limit=50,
                )
            )

        except Exception:

            logger.exception(
                "[%s] Erro lendo DM %s",
                account["name"],
                channel_id,
            )

            continue

        messages.sort(
            key=lambda message:
                message.get(
                    "timestampMilli",
                    0,
                )
        )

        for message in messages:

            message_id = (
                message.get("id")
            )

            author_id = (
                message.get("author")
            )

            if not message_id:
                continue

            # Ignora mensagens enviadas pela própria
            # conta de suporte.
            if (
                str(author_id)
                == str(support_user_id)
            ):
                continue

            if is_message_processed(
                message_id=message_id,
                support_account=account[
                    "key"
                ],
            ):
                continue

            text = (
                extract_message_text(
                    message
                )
            )

            # ----------------------------------------------------
            # NÃO É TICKET
            # ----------------------------------------------------

            if not is_ticket_template(
                text=text,
                support_account=account[
                    "key"
                ],
            ):

                logger.info(
                    "[%s] Mensagem %s ignorada: "
                    "não corresponde ao template.",
                    account["name"],
                    message_id,
                )

                try:

                    send_ticket_instructions(
                        account=account,
                        pumble=pumble,
                        channel_id=channel_id,
                    )

                except Exception:

                    logger.exception(
                        "[%s] Erro enviando "
                        "instruções para DM %s.",
                        account["name"],
                        channel_id,
                    )

                mark_message_processed(
                    message_id=message_id,
                    support_account=account[
                        "key"
                    ],
                    channel_id=channel_id,
                    plaky_item_id=None,
                )

                continue

            # ----------------------------------------------------
            # TICKET VÁLIDO
            # ----------------------------------------------------

            title = (
                build_ticket_title(
                    message
                )
            )

            requested_at = (
                message.get("timestamp")
                or str(
                    message.get(
                        "timestampMilli"
                    )
                )
            )

            (
                requester_id,
                requester_name,
            ) = resolve_requester(
                message=message,
                users_by_id=users_by_id,
            )

            ticket_code = (
                generate_ticket_code(
                    support_account=account[
                        "key"
                    ],
                    requested_at=(
                        requested_at
                    ),
                )
            )

            plaky_title = (
                f"[{ticket_code}] "
                f"{title}"
            )

            plaky_description = (
                build_plaky_description(
                    requester_name=(
                        requester_name
                    ),
                    text=text,
                )
            )

            logger.info(
                "[%s] Novo ticket %s "
                "de %s: %s",
                account["name"],
                ticket_code,
                requester_name,
                title,
            )

            try:

                response = (
                    plaky.create_item(
                        board_id=account[
                            "plaky_board_id"
                        ],
                        group_id=account[
                            "plaky_group_id"
                        ],
                        title=plaky_title,
                    )
                )

                plaky_item_id = (
                    extract_plaky_item_id(
                        response
                    )
                )

                if not plaky_item_id:

                    raise RuntimeError(
                        "Plaky criou o item, "
                        "mas não retornou itemId."
                    )

                item_id = int(
                    plaky_item_id
                )

                # DESCRIPTION
                try:

                    plaky.set_description(
                        board_id=account[
                            "plaky_board_id"
                        ],
                        item_id=item_id,
                        description=(
                            plaky_description
                        ),
                    )

                except Exception:

                    logger.exception(
                        "[%s] Ticket %s criado, "
                        "mas Description falhou.",
                        account["name"],
                        ticket_code,
                    )

                # DATE
                try:

                    plaky.set_date(
                        board_id=account[
                            "plaky_board_id"
                        ],
                        item_id=item_id,
                        requested_at=(
                            requested_at
                        ),
                    )

                except Exception:

                    logger.exception(
                        "[%s] Ticket %s criado, "
                        "mas Date falhou.",
                        account["name"],
                        ticket_code,
                    )

                # IMPORTANTE:
                # persistimos antes de qualquer
                # mensagem de confirmação/notificação.
                create_ticket(
                    ticket_code=ticket_code,
                    support_account=account[
                        "key"
                    ],
                    requester_id=requester_id,
                    requester_name=(
                        requester_name
                    ),
                    channel_id=channel_id,
                    message_id=message_id,
                    plaky_item_id=(
                        plaky_item_id
                    ),
                    title=title,
                    description=text,
                    requested_at=(
                        requested_at
                    ),
                    last_status="0",
                )

                mark_message_processed(
                    message_id=message_id,
                    support_account=account[
                        "key"
                    ],
                    channel_id=channel_id,
                    plaky_item_id=(
                        plaky_item_id
                    ),
                )

                # CONFIRMA SOLICITANTE
                try:

                    send_ticket_created_confirmation(
                        account=account,
                        pumble=pumble,
                        channel_id=channel_id,
                        ticket_code=(
                            ticket_code
                        ),
                    )

                except Exception:

                    logger.exception(
                        "[%s] Ticket %s criado, "
                        "mas confirmação falhou.",
                        account["name"],
                        ticket_code,
                    )

                # NOTIFICA RESPONSÁVEIS
                notify_support_team(
                    account=account,
                    pumble=pumble,
                    channels=channels,
                    support_user_id=(
                        support_user_id
                    ),
                    requester_id=(
                        requester_id
                    ),
                    requester_name=(
                        requester_name
                    ),
                    ticket_code=(
                        ticket_code
                    ),
                    title=title,
                )

                logger.info(
                    "[%s] Ticket %s criado "
                    "com sucesso. Plaky=%s",
                    account["name"],
                    ticket_code,
                    plaky_item_id,
                )

            except Exception:

                logger.exception(
                    "[%s] Erro criando ticket "
                    "para mensagem %s",
                    account["name"],
                    message_id,
                )


# ============================================================
# MONITORAMENTO DE STATUS
# ============================================================


def normalize_plaky_status(
    status,
) -> str | None:

    if status is None:
        return None

    if isinstance(
        status,
        (str, int),
    ):
        return str(status)

    if isinstance(
        status,
        dict,
    ):

        for key in (
            "id",
            "value",
            "key",
        ):

            value = status.get(key)

            if value is not None:
                return str(value)

        title = status.get(
            "title"
        )

        if title:

            normalized_title = (
                str(title)
                .strip()
                .lower()
            )

            return {
                "backlog": "0",
                "to do": "1",
                "todo": "1",
                "in progress": "2",
                "blocked": "4",
                "done": "3",
            }.get(
                normalized_title,
                str(title),
            )

    return str(status)


def monitor_ticket_statuses(
    plaky: PlakyClient,
):

    tickets = (
        get_monitored_tickets()
    )

    if not tickets:
        return

    for ticket in tickets:

        ticket_code = (
            ticket["ticket_code"]
        )

        previous_status = (
            ticket["last_status"]
        )

        # Ticket concluído deixa de ser consultado.
        if (
            str(previous_status)
            == "3"
        ):
            continue

        account = (
            get_support_account(
                ticket[
                    "support_account"
                ]
            )
        )

        if not account:
            continue

        try:

            raw_status = (
                plaky.get_item_status(
                    board_id=account[
                        "plaky_board_id"
                    ],
                    item_id=int(
                        ticket[
                            "plaky_item_id"
                        ]
                    ),
                )
            )

            current_status = (
                normalize_plaky_status(
                    raw_status
                )
            )

        except Exception:

            logger.exception(
                "[%s] Erro consultando "
                "status do ticket %s.",
                account["name"],
                ticket_code,
            )

            continue

        if current_status is None:
            continue

        previous_status = (
            str(previous_status)
            if previous_status
            is not None
            else None
        )

        if previous_status is None:

            update_ticket_status(
                ticket_code=ticket_code,
                status=current_status,
            )

            continue

        if (
            current_status
            == previous_status
        ):
            continue

        logger.info(
            "[%s] Ticket %s mudou: %s -> %s",
            account["name"],
            ticket_code,
            PLAKY_STATUS_NAMES.get(
                previous_status,
                previous_status,
            ),
            PLAKY_STATUS_NAMES.get(
                current_status,
                current_status,
            ),
        )

        # Persiste ANTES da notificação.
        update_ticket_status(
            ticket_code=ticket_code,
            status=current_status,
        )

        message = (
            get_status_changed_message(
                ticket_code=ticket_code,
                status=current_status,
            )
        )

        if not message:
            continue

        try:

            pumble = PumbleClient(
                account[
                    "pumble_api_key"
                ]
            )

            pumble.send_message(
                channel_id=ticket[
                    "pumble_channel_id"
                ],
                text=message,
                as_bot=False,
            )

        except Exception:

            logger.exception(
                "[%s] Status atualizado, "
                "mas notificação do "
                "ticket %s falhou.",
                account["name"],
                ticket_code,
            )


# ============================================================
# MAIN
# ============================================================


def main():

    logger.info(
        "Iniciando integração "
        "Pumble -> Plaky"
    )

    init_database()

    plaky = PlakyClient()

    while True:

        for account in SUPPORT_ACCOUNTS:

            try:

                process_account(
                    account=account,
                    plaky=plaky,
                )

            except Exception:

                logger.exception(
                    "Erro processando conta %s",
                    account["name"],
                )

        try:

            monitor_ticket_statuses(
                plaky=plaky
            )

        except Exception:

            logger.exception(
                "Erro geral durante "
                "monitoramento dos tickets."
            )

        logger.info(
            "Próxima consulta em %s segundos.",
            POLL_INTERVAL_SECONDS,
        )

        time.sleep(
            POLL_INTERVAL_SECONDS
        )


if __name__ == "__main__":
    main()