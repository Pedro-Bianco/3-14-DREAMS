"""Gmail MCP server over IMAP/SMTP with an app password.

Started by the app as its own process (`--mcp gmail`); account and password arrive through
environment variables (the password lives in the app's secret store). Standard library + MCP SDK only.
Reading and searching use PEEK: opening an e-mail through the assistant does not mark it as read.
"""

import email
import email.policy
import html
import imaplib
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

IMAP = ("imap.gmail.com", 993)
SMTP = ("smtp.gmail.com", 465)
_MAX_LIST = 20
LOGIN_REFUSED = ("O Google recusou o login. Confira o endereço e use uma senha de app (não a senha "
                  "normal): myaccount.google.com/apppasswords — exige a verificação em duas etapas.")

SERVER = MCPServer(
    "gmail",
    instructions=("E-mails da conta Gmail do usuário. Para achar e-mails use buscar_emails; para o "
                  "texto completo use ler_email com o id da busca. Para responder, use o id do "
                  "e-mail em responder_a_id."))


def _account() -> tuple[str, str]:
    return os.environ.get("GMAIL_ACCOUNT", ""), os.environ.get("GMAIL_APP_PASSWORD", "")


def _imap() -> imaplib.IMAP4_SSL:
    """ToolError: the SDK only passes ToolError text to the model; anything else becomes a "generic error"."""
    account, password = _account()
    try:
        connection = imaplib.IMAP4_SSL(*IMAP, timeout=30)
        connection.login(account, password)
    except imaplib.IMAP4.error:
        raise ToolError(LOGIN_REFUSED) from None
    except OSError as e:
        raise ToolError(f"Não consegui falar com o Gmail ({e}). Confira a internet.") from None
    return connection


def check_login(account: str, password: str) -> str | None:
    """For the connections screen: None if the login worked, otherwise the message for the person."""
    try:
        connection = imaplib.IMAP4_SSL(*IMAP, timeout=15)
        connection.login(account, password)
        connection.logout()
        return None
    except imaplib.IMAP4.error:
        return LOGIN_REFUSED
    except OSError as e:
        return f"Não consegui falar com o Gmail ({e}). Confira a internet."


def _query(de: str, assunto: str, desde_dias: int, so_nao_lidos: bool, texto: str) -> str:
    """Gmail's own search syntax (X-GM-RAW): the same as the search box on the website."""
    parts = [f'from:"{de}"' if de else "", f'subject:"{assunto}"' if assunto else "",
              f"newer_than:{max(1, int(desde_dias))}d" if desde_dias else "",
              "is:unread" if so_nao_lidos else "", texto]
    return " ".join(p for p in parts if p).strip() or "in:inbox"


def _header(message) -> str:
    de = parseaddr(str(message.get("From", "")))
    return (f"de: {de[0] or de[1]} <{de[1]}> | assunto: {message.get('Subject', '(sem assunto)')} "
            f"| data: {message.get('Date', '')}")


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
def buscar_emails(de: str = "", assunto: str = "", desde_dias: int = 7, so_nao_lidos: bool = False,
                  texto: str = "", maximo: int = 10) -> str:
    """Procura e-mails na caixa de entrada. de: remetente (nome ou e-mail); assunto: parte do
    assunto; desde_dias: só dos últimos N dias (0 = qualquer data); so_nao_lidos; texto: palavras
    no corpo. Devolve os mais novos primeiro, com o id para ler_email."""
    connection = _imap()
    try:
        connection.select("INBOX", readonly=True)
        connection.literal = _query(de, assunto, desde_dias, so_nao_lidos, texto).encode("utf-8")
        _, data = connection.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        uids = (data[0] or b"").split()[::-1][:max(1, min(int(maximo), _MAX_LIST))]
        if not uids:
            return "Nenhum e-mail encontrado."
        lines = []
        for uid in uids:
            _, parts = connection.uid("FETCH", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            header = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            loaded = b"\\Seen" in parts[0][0]
            lines.append(f"id {uid.decode()} | {_header(header)}{'' if loaded else ' | NÃO LIDO'}")
        return "\n".join(lines)
    finally:
        connection.logout()


def _text(message) -> str:
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        return "(sem texto)"
    content = body.get_content()
    if body.get_content_type() == "text/html":
        content = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", content)))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", content)).strip()


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=True))
def ler_email(id: str) -> str:  # noqa: A002 — nome que o modelo vê
    """Lê o texto de um e-mail pelo id que a busca devolveu (anexos não são abertos)."""
    connection = _imap()
    try:
        connection.select("INBOX", readonly=True)
        _, parts = connection.uid("FETCH", str(id), "(BODY.PEEK[])")
        if not parts or parts[0] is None or not isinstance(parts[0], tuple):
            return f"Não achei o e-mail {id}."
        message = email.message_from_bytes(parts[0][1], policy=email.policy.default)
        attachments = [a.get_filename() for a in message.iter_attachments() if a.get_filename()]
        footer = f"\n[anexos não abertos: {', '.join(attachments)}]" if attachments else ""
        return f"{_header(message)}\n\n{_text(message)}{footer}"
    finally:
        connection.logout()


def _build(para: str, assunto: str, texto: str, responder_a_id: str, connection) -> EmailMessage:
    account, _ = _account()
    message = EmailMessage()
    message["From"] = formataddr(("", account))
    message["To"] = para
    message["Subject"] = assunto
    if responder_a_id:
        connection.select("INBOX", readonly=True)
        _, parts = connection.uid("FETCH", str(responder_a_id),
                                "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID REFERENCES SUBJECT FROM)])")
        if parts and isinstance(parts[0], tuple):
            original = email.message_from_bytes(parts[0][1], policy=email.policy.default)
            if original.get("Message-ID"):
                message["In-Reply-To"] = original["Message-ID"]
                message["References"] = f"{original.get('References', '')} {original['Message-ID']}".strip()
            if not para:
                message.replace_header("To", parseaddr(str(original.get("From", "")))[1])
            if not assunto:
                previous = str(original.get("Subject", ""))
                message.replace_header("Subject", previous if previous.lower().startswith("re:") else f"Re: {previous}")
    message.set_content(texto)
    return message


def _drafts_folder(connection) -> str:
    """The name changes with the account language ([Gmail]/Drafts, [Gmail]/Rascunhos): the \\Drafts flag is what counts."""
    _, folders = connection.list()
    for line in folders or []:
        texto = line.decode(errors="replace")
        if "\\Drafts" in texto:
            return texto.rsplit(' "/" ', 1)[-1].strip()
    return '"[Gmail]/Drafts"'


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True))
def criar_rascunho(para: str = "", assunto: str = "", texto: str = "", responder_a_id: str = "") -> str:
    """Guarda um rascunho nos Rascunhos do Gmail, sem enviar. Para responder, passe
    responder_a_id (o id da busca); destinatário e assunto vêm do e-mail original."""
    connection = _imap()
    try:
        message = _build(para, assunto, texto, responder_a_id, connection)
        connection.append(_drafts_folder(connection), "(\\Draft)", None, message.as_bytes())
        return f"Rascunho guardado para {message['To']}: {message['Subject']}"
    finally:
        connection.logout()


@SERVER.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True))
def enviar_email(para: str = "", assunto: str = "", texto: str = "", responder_a_id: str = "") -> str:
    """Envia um e-mail. Para responder, passe responder_a_id (o id da busca); destinatário e
    assunto vêm do e-mail original."""
    account, password = _account()
    connection = _imap()
    try:
        message = _build(para, assunto, texto, responder_a_id, connection)
    finally:
        connection.logout()
    if not message["To"]:
        return "Falta o destinatário."
    try:
        with smtplib.SMTP_SSL(*SMTP, timeout=30) as smtp:
            smtp.login(account, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise ToolError(LOGIN_REFUSED) from None
    except OSError as e:
        raise ToolError(f"O e-mail não foi enviado: {e}") from None
    return f"E-mail enviado para {message['To']}: {message['Subject']}"
