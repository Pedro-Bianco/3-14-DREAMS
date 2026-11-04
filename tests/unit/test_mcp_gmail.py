"""Servidor MCP do Gmail com IMAP/SMTP falsos.

O servidor roda pelo protocolo de verdade, em memória (`Client(SERVIDOR)`); só a rede do
Google é trocada por objetos falsos com e-mails fictícios.
"""

import asyncio
import email
import email.policy
import imaplib
from email.message import EmailMessage

import pytest
from mcp import Client

from pidreams.mcp import gmail


def _message(sender, subject, text, message_id, attachment=False, html=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "eu@example.com", subject
    m["Date"], m["Message-ID"] = "Thu, 29 Oct 2026 10:00:00 -0300", message_id
    if html:
        m.set_content(f"<html><body><p>{text}</p><script>x()</script></body></html>", subtype="html")
    else:
        m.set_content(text)
    if attachment:
        m.add_attachment(b"%PDF ficticio", maintype="application", subtype="pdf", filename="boleto.pdf")
    return m.as_bytes()


class _FakeImap:
    box = {}                      # uid -> (bytes, lido)
    drafts: list = []
    searches: list = []
    right_password = "abcd efgh ijkl mnop"

    def __init__(self, *_a, **_k):
        self.literal = None

    def login(self, _account, password):
        if password != self.right_password:
            raise imaplib.IMAP4.error("[AUTHENTICATIONFAILED] Invalid credentials")

    def select(self, *_a, **_k):
        return "OK", [b"3"]

    def uid(self, command, *args):
        if command == "SEARCH":
            query_text = self.literal.decode()
            self.searches.append(query_text)
            found = [u for u, (b, _) in self.box.items()
                       if not ("from:" in query_text and query_text.split('from:"')[1].split('"')[0].lower()
                               not in b.decode(errors="ignore").lower())]
            return "OK", [" ".join(found).encode()]
        uid = args[0].decode() if isinstance(args[0], bytes) else args[0]
        parts = args[1]
        if uid not in self.box:
            return "OK", [None]
        body, loaded = self.box[uid]
        flags = b"(FLAGS (\\Seen)" if loaded else b"(FLAGS ()"
        if "HEADER.FIELDS" in parts:
            body = body.split(b"\n\n", 1)[0] + b"\n\n"
        return "OK", [(flags + b" BODY[] {1}", body), b")"]

    def list(self):
        return "OK", [b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Rascunhos"']

    def append(self, folder, flags, _data, message):
        self.drafts.append((folder, flags, message))

    def logout(self):
        pass


class _FakeSmtp:
    sent: list = []

    def __init__(self, *_a, **_k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def login(self, _account, _password):
        pass

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture
def account(monkeypatch):
    _FakeImap.box = {
        "101": (_message("Banco Fictício <avisos@example.org>", "Fatura de novembro", "Sua fatura fictícia é de R$ 320.", "<a1@banco>"), True),
        "102": (_message("Ana Exemplo <ana@example.com>", "Almoço sexta?", "Bora almoçar sexta?", "<a2@ex>", attachment=True), False),
        "103": (_message("Escola Fictícia <escola@example.org>", "Reunião", "Reunião de pais dia 12.", "<a3@esc>", html=True), False),
    }
    _FakeImap.drafts, _FakeImap.searches, _FakeSmtp.sent = [], [], []
    monkeypatch.setattr(gmail.imaplib, "IMAP4_SSL", _FakeImap)
    monkeypatch.setattr(gmail.smtplib, "SMTP_SSL", _FakeSmtp)
    monkeypatch.setenv("GMAIL_ACCOUNT", "eu@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", _FakeImap.right_password)


def _call(tool, arguments):
    async def run():
        async with Client(gmail.SERVER) as client:
            r = await client.call_tool(tool, arguments)
            return r.is_error, "\n".join(b.text for b in r.content)
    return asyncio.run(run())


def test_ferramentas_e_anotacoes():
    async def list_items():
        async with Client(gmail.SERVER) as client:
            return {t.name: bool(t.annotations and t.annotations.read_only_hint)
                    for t in (await client.list_tools()).tools}
    assert asyncio.run(list_items()) == {"buscar_emails": True, "ler_email": True,
                                     "criar_rascunho": False, "enviar_email": False}


def test_busca_usa_a_sintaxe_do_gmail_e_lista_os_mais_novos(account):
    error, text = _call("buscar_emails", {"de": "ana", "so_nao_lidos": True, "desde_dias": 3})
    assert not error and _FakeImap.searches[-1] == 'from:"ana" newer_than:3d is:unread'
    assert "id 102" in text and "Almoço sexta?" in text and "NÃO LIDO" in text
    error, text = _call("buscar_emails", {})
    assert text.index("id 103") < text.index("id 101")            # mais novo primeiro


def test_leitura_sem_anexo_e_html_vira_texto(account):
    _, text = _call("ler_email", {"id": "102"})
    assert "Bora almoçar sexta?" in text and "anexos não abertos: boleto.pdf" in text
    _, text = _call("ler_email", {"id": "103"})
    assert "Reunião de pais dia 12." in text and "<p>" not in text and "x()" not in text
    _, text = _call("ler_email", {"id": "999"})
    assert "Não achei" in text


def test_rascunho_e_envio_respondendo(account):
    _, text = _call("criar_rascunho", {"texto": "Confirmo, até sexta!", "responder_a_id": "102"})
    folder, flags, raw = _FakeImap.drafts[-1]
    assert folder == '"[Gmail]/Rascunhos"' and "\\Draft" in flags
    reply = email.message_from_bytes(raw, policy=email.policy.default)
    assert reply["In-Reply-To"] == "<a2@ex>" and reply["Subject"] == "Re: Almoço sexta?"
    assert "ana@example.com" in text
    _, text = _call("enviar_email", {"para": "ana@example.com", "assunto": "Oi", "texto": "Teste fictício."})
    assert "enviado" in text and _FakeSmtp.sent[-1]["To"] == "ana@example.com"


def test_login_recusado_vira_mensagem_legivel(account, monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "senha-errada")
    error, text = _call("buscar_emails", {})
    assert error and "senha de app" in text
    assert "senha de app" in gmail.check_login("eu@example.com", "senha-errada")
    assert gmail.check_login("eu@example.com", _FakeImap.right_password) is None
