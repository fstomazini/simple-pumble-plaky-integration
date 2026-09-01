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
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURAÇÃO DA RESPOSTA AUTOMÁTICA
# ============================================================

AUTO_REPLY_COOLDOWN_SECONDS = 10 * 60

last_auto_reply = {}


# ============================================================
# STATUS PLAKY
# ============================================================

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
        return """Olá! 👋

Para registrar um problema no LiderHub, envie sua solicitação em uma única mensagem usando este modelo:

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
    ticket_code: str,
    support_account: str,
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
            f"📋 O chamado {ticket_code} entrou na fila "
            "de atendimento."
        )

    if status == "2":
        return (
            f"🔄 O chamado {ticket_code} está em atendimento."
        )

    if status == "4":
        return (
            f"⏸️ O chamado {ticket_code} está temporariamente "
            "bloqueado.\n\n"
            "Caso seja necessária alguma informação adicional, "
            "o suporte entrará em contato."
        )

    if status == "3":
        return (
            f"✅ O chamado {ticket_code} foi concluído."
        )

    return None


# ============================================================
# MENSAGENS / TEMPLATE
# ============================================================


def extract_message_text(
    message: dict,
) -> str:

    text = message.get("text")

    if isinstance(text, str) and text.strip():
        return text.strip()

    texts = []

    def walk(value):
        if isinstance(value, dict):
            if value.get("type") == "text":
                block_text = value.get("text")

                if isinstance(block_text, str):
                    texts.append(block_text)

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
    return text.lower().strip()


def extract_template_field(
    text: str,
    field_name: str,
) -> str | None:

    if not text:
        return None

    target = field_name.lower().strip()

    for line in text.splitlines():
        line = line.strip()

        if not line or ":" not in line:
            continue

        key, value = line.split(
            ":",
            1,
        )

        if key.lower().strip() == target:
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

    target = field_name.lower().strip()

    for line in text.splitlines():
        line = line.strip()

        if ":" not in line:
            continue

        key, _ = line.split(
            ":",
            1,
        )

        if key.lower().strip() == target:
            return True

    return False


def is_ticket_template(
    text: str,
    support_account: str,
) -> bool:

    if not text:
        return False

    normalized = normalize_text(
        text
    )

    if "#novo-ticket" not in normalized:
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
        logger.warning(
            "Conta de suporte desconhecida: %s",
            support_account,
        )

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

    if not text:
        return "Nova solicitação via Pumble"

    problem = extract_template_field(
        text=text,
        field_name="Problema",
    )

    if problem:
        title = problem

    else:
        title = (
            "Solicitação sem descrição "
            "do problema"
        )

    max_length = 120

    if len(title) <= max_length:
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
# RESPOSTA AUTOMÁTICA
# ============================================================


def can_send_auto_reply(
    support_account: str,
    channel_id: str,
) -> bool:

    key = (
        support_account,
        channel_id,
    )

    last_sent = last_auto_reply.get(
        key
    )

    if last_sent is None:
        return True

    elapsed = (
        time.time()
        - last_sent
    )

    return (
        elapsed
        >= AUTO_REPLY_COOLDOWN_SECONDS
    )


def register_auto_reply(
    support_account: str,
    channel_id: str,
):

    key = (
        support_account,
        channel_id,
    )

    last_auto_reply[key] = (
        time.time()
    )


def send_ticket_instructions(
    account: dict,
    pumble: PumbleClient,
    channel_id: str,
):

    if not can_send_auto_reply(
        support_account=account["key"],
        channel_id=channel_id,
    ):
        logger.info(
            "[%s] Instruções não enviadas "
            "para DM %s: cooldown ativo.",
            account["name"],
            channel_id,
        )

        return

    template_message = (
        get_ticket_template_message(
            account["key"]
        )
    )

    pumble.send_message(
        channel_id=channel_id,
        text=template_message,
        as_bot=False,
    )

    register_auto_reply(
        support_account=account["key"],
        channel_id=channel_id,
    )

    logger.info(
        "[%s] Instruções de abertura "
        "de ticket enviadas para DM %s.",
        account["name"],
        channel_id,
    )


def send_ticket_created_confirmation(
    account: dict,
    pumble: PumbleClient,
    channel_id: str,
    ticket_code: str,
):

    confirmation_message = (
        get_ticket_created_message(
            ticket_code=ticket_code,
            support_account=account["key"],
        )
    )

    pumble.send_message(
        channel_id=channel_id,
        text=confirmation_message,
        as_bot=False,
    )

    logger.info(
        "[%s] Confirmação do ticket %s "
        "enviada ao solicitante.",
        account["name"],
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

    item_id = response.get(
        "id"
    )

    if item_id is not None:
        return str(item_id)

    data = response.get(
        "data"
    )

    if isinstance(
        data,
        dict,
    ):
        item_id = data.get(
            "id"
        )

        if item_id is not None:
            return str(
                item_id
            )

    return None


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
            channel.get(
                "channelType"
            )
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

    users = (
        pumble.list_users()
    )

    return {
        user["id"]: user
        for user in users
        if (
            isinstance(
                user,
                dict,
            )
            and user.get("id")
        )
    }


def resolve_requester(
    message: dict,
    users_by_id: dict,
):

    requester_id = (
        message.get(
            "author"
        )
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
# CONTA
# ============================================================


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
                author_id
                == support_user_id
            ):
                continue

            mark_message_processed(
                message_id=message_id,
                support_account=account["key"],
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
# PROCESSAMENTO DE NOVAS MENSAGENS
# ============================================================


def process_account(
    account: dict,
    plaky: PlakyClient,
):

    pumble = PumbleClient(
        account[
            "pumble_api_key"
        ]
    )

    my_info = (
        pumble.get_my_info()
    )

    support_user_id = (
        my_info.get("id")
    )

    if not support_user_id:
        raise RuntimeError(
            f"Não foi possível identificar "
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

            if (
                author_id
                == support_user_id
            ):
                continue

            if is_message_processed(
                message_id=message_id,
                support_account=account["key"],
            ):
                continue

            text = (
                extract_message_text(
                    message
                )
            )

            # ==================================================
            # NÃO É UM TICKET
            # ==================================================

            if not is_ticket_template(
                text=text,
                support_account=account["key"],
            ):

                logger.info(
                    "[%s] Mensagem %s ignorada: "
                    "não corresponde ao template "
                    "#NOVO-TICKET.",
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
                        "[%s] Erro ao enviar "
                        "instruções de abertura "
                        "de ticket para DM %s.",
                        account["name"],
                        channel_id,
                    )

                mark_message_processed(
                    message_id=message_id,
                    support_account=account["key"],
                    channel_id=channel_id,
                    plaky_item_id=None,
                )

                continue

            # ==================================================
            # NOVO TICKET
            # ==================================================

            title = (
                build_ticket_title(
                    message
                )
            )

            requested_at = (
                message.get(
                    "timestamp"
                )
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
                    support_account=account["key"],
                    requested_at=requested_at,
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

                # ------------------------------------------------
                # DESCRIPTION
                # ------------------------------------------------

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
                        "mas ocorreu erro ao preencher "
                        "Description.",
                        account["name"],
                        ticket_code,
                    )

                # ------------------------------------------------
                # DATE
                # ------------------------------------------------

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
                        "mas ocorreu erro ao preencher "
                        "Date.",
                        account["name"],
                        ticket_code,
                    )

                # ------------------------------------------------
                # SQLITE
                # ------------------------------------------------

                create_ticket(
                    ticket_code=(
                        ticket_code
                    ),
                    support_account=account[
                        "key"
                    ],
                    requester_id=(
                        requester_id
                    ),
                    requester_name=(
                        requester_name
                    ),
                    channel_id=(
                        channel_id
                    ),
                    message_id=(
                        message_id
                    ),
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
                    message_id=(
                        message_id
                    ),
                    support_account=account[
                        "key"
                    ],
                    channel_id=(
                        channel_id
                    ),
                    plaky_item_id=(
                        plaky_item_id
                    ),
                )

                # ------------------------------------------------
                # CONFIRMAÇÃO
                # ------------------------------------------------

                try:
                    send_ticket_created_confirmation(
                        account=account,
                        pumble=pumble,
                        channel_id=channel_id,
                        ticket_code=ticket_code,
                    )

                except Exception:
                    logger.exception(
                        "[%s] Ticket %s foi criado, "
                        "mas ocorreu erro ao enviar "
                        "a confirmação pelo Pumble.",
                        account["name"],
                        ticket_code,
                    )

                logger.info(
                    "[%s] Ticket %s criado "
                    "com sucesso. "
                    "Solicitante=%s | "
                    "PumbleUser=%s | "
                    "PumbleMessage=%s | "
                    "Plaky=%s",
                    account["name"],
                    ticket_code,
                    requester_name,
                    requester_id,
                    message_id,
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
            value = status.get(
                key
            )

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

            by_title = {
                "backlog": "0",
                "to do": "1",
                "todo": "1",
                "in progress": "2",
                "blocked": "4",
                "done": "3",
            }

            return by_title.get(
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

    logger.info(
        "Monitorando status de %s tickets.",
        len(tickets),
    )

    for ticket in tickets:

        ticket_code = (
            ticket["ticket_code"]
        )

        support_account = (
            ticket["support_account"]
        )

        previous_status = (
            ticket["last_status"]
        )

        if (
            str(previous_status)
            == "3"
        ):
            continue

        account = (
            get_support_account(
                support_account
            )
        )

        if not account:
            logger.warning(
                "Conta de suporte não encontrada "
                "para ticket %s: %s",
                ticket_code,
                support_account,
            )

            continue

        plaky_item_id = (
            ticket["plaky_item_id"]
        )

        if not plaky_item_id:
            continue

        try:
            raw_status = (
                plaky.get_item_status(
                    board_id=account[
                        "plaky_board_id"
                    ],
                    item_id=int(
                        plaky_item_id
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
                "[%s] Erro consultando status "
                "do ticket %s no Plaky.",
                account["name"],
                ticket_code,
            )

            continue

        if current_status is None:
            logger.warning(
                "[%s] Não foi possível identificar "
                "o status do ticket %s.",
                account["name"],
                ticket_code,
            )

            continue

        previous_status = (
            str(previous_status)
            if previous_status is not None
            else None
        )

        # ----------------------------------------------------
        # PRIMEIRA CONSULTA
        # ----------------------------------------------------

        if previous_status is None:

            update_ticket_status(
                ticket_code=ticket_code,
                status=current_status,
            )

            logger.info(
                "[%s] Status inicial do ticket %s: %s",
                account["name"],
                ticket_code,
                PLAKY_STATUS_NAMES.get(
                    current_status,
                    current_status,
                ),
            )

            continue

        # ----------------------------------------------------
        # STATUS NÃO MUDOU
        # ----------------------------------------------------

        if (
            current_status
            == previous_status
        ):
            continue

        logger.info(
            "[%s] Ticket %s mudou de status: "
            "%s -> %s",
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

            logger.info(
                "[%s] Alteração de status "
                "do ticket %s enviada "
                "ao solicitante.",
                account["name"],
                ticket_code,
            )

        except Exception:
            logger.exception(
                "[%s] Status do ticket %s "
                "foi atualizado para %s, "
                "mas ocorreu erro ao notificar "
                "o solicitante.",
                account["name"],
                ticket_code,
                current_status,
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

    plaky = (
        PlakyClient()
    )

    while True:

        # ----------------------------------------------------
        # NOVAS SOLICITAÇÕES
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # STATUS DOS TICKETS
        # ----------------------------------------------------

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