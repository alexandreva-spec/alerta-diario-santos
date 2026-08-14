"""
Robô diário do alerta de Diário Oficial de Santos.

Fluxo:
1. Baixa o PDF da edição do dia (ou da data passada via --data).
2. Extrai o texto de cada página.
3. Compara com os termos de busca ativos cadastrados no Supabase.
4. Para cada novo match, grava em `matches` e envia e-mail (com o PDF em
   anexo) para o dono do termo, com cópia para o(s) admin(s).

Variáveis de ambiente esperadas (ver ../README.md):
  SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY, EMAIL_REMETENTE
"""

import argparse
import base64
import io
import os
import re
import sys
from datetime import date, datetime

import pdfplumber
import requests
import resend
from supabase import Client, create_client
from unidecode import unidecode

DOWNLOAD_URL = "https://diariooficial.santos.sp.gov.br/edicoes/inicio/download/{data}"
SITE_URL = "https://alexandreva-spec.github.io/alerta-diario-santos/"


def normaliza(texto: str) -> str:
    """minúsculas + sem acento, para comparação robusta."""
    return unidecode(texto or "").lower()


def baixa_edicao(data_str: str) -> bytes:
    url = DOWNLOAD_URL.format(data=data_str)
    resp = requests.get(url, timeout=60)
    if resp.status_code == 404:
        raise FileNotFoundError(f"Sem edição publicada em {data_str} (404 em {url})")
    resp.raise_for_status()
    if resp.headers.get("content-type", "").split(";")[0] not in (
        "application/pdf",
        "application/octet-stream",
    ):
        raise ValueError(
            f"Resposta de {url} não parece ser um PDF "
            f"(content-type={resp.headers.get('content-type')!r})"
        )
    return resp.content


def constroi_regex(tipo: str, valor: str) -> re.Pattern:
    valor_norm = normaliza(valor)
    escaped = re.escape(valor_norm)
    if tipo == "nome_completo":
        # word boundary nas duas pontas evita "Ana Paula" casar com "Ana Paulatino"
        return re.compile(rf"\b{escaped}\b")
    # palavra_chave: substring simples (ex.: "processo 1234", "licitação")
    return re.compile(escaped)


def extrai_trecho(pagina_texto_original: str, match_pos: int, janela: int = 120) -> str:
    ini = max(0, match_pos - janela)
    fim = min(len(pagina_texto_original), match_pos + janela)
    return pagina_texto_original[ini:fim].strip()


def busca_termos(paginas_norm: list[str], paginas_original: list[str], termos: list[dict]):
    """Gera (termo, pagina_numero[1-based], trecho) para cada match encontrado."""
    for termo in termos:
        regex = constroi_regex(termo["tipo"], termo["valor"])
        for i, texto_norm in enumerate(paginas_norm):
            m = regex.search(texto_norm)
            if m:
                trecho = extrai_trecho(paginas_original[i], m.start())
                yield termo, i + 1, trecho


def carrega_termos_ativos(sb: Client) -> list[dict]:
    """Busca search_terms ativos com o usuário (ativo + dono ativo) já embutido."""
    resp = (
        sb.table("search_terms")
        .select("id, tipo, valor, user_id, users!inner(id, nome, email, ativo)")
        .eq("ativo", True)
        .eq("users.ativo", True)
        .execute()
    )
    return resp.data or []


def carrega_admins(sb: Client) -> list[str]:
    resp = sb.table("users").select("email").eq("is_admin", True).eq("ativo", True).execute()
    return [r["email"] for r in (resp.data or [])]


def ja_notificado(sb: Client, search_term_id: str, data_edicao: str) -> bool:
    resp = (
        sb.table("matches")
        .select("id")
        .eq("search_term_id", search_term_id)
        .eq("data_edicao", data_edicao)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def registra_match(sb: Client, termo: dict, data_edicao: str, pagina: int, trecho: str):
    sb.table("matches").insert(
        {
            "user_id": termo["user_id"],
            "search_term_id": termo["id"],
            "data_edicao": data_edicao,
            "pagina": pagina,
            "trecho": trecho,
        }
    ).execute()


def envia_email(destinatarios: list[str], nome: str, termo_valor: str, pagina: int, trecho: str,
                 data_edicao: str, pdf_bytes: bytes, remetente: str):
    assunto = f"[Diário Oficial de Santos] '{termo_valor}' encontrado na edição de {data_edicao}"
    corpo = f"""
    <p>Olá, {nome}.</p>
    <p>O termo <b>{termo_valor}</b> foi encontrado na edição do Diário Oficial de Santos de
    <b>{data_edicao}</b>, na página {pagina}.</p>
    <p><i>Trecho encontrado:</i><br>&laquo;...{trecho}...&raquo;</p>
    <p>O PDF completo da edição está anexado a este e-mail.</p>
    <hr>
    <p style="font-size:12px;color:#666;">
    Não quer mais receber estes alertas? Acesse <a href="{SITE_URL}">{SITE_URL}</a>,
    entre com seu e-mail e clique em "Pausar todos os alertas" (ou exclua o alerta
    específico em "Meus alertas").
    </p>
    """
    resend.Emails.send(
        {
            "from": remetente,
            "to": destinatarios,
            "subject": assunto,
            "html": corpo,
            "attachments": [
                {
                    "filename": f"diario_oficial_santos_{data_edicao}.pdf",
                    "content": list(base64.b64encode(pdf_bytes)),
                }
            ],
        }
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=None, help="Data da edição (AAAA-MM-DD). Padrão: hoje.")
    args = parser.parse_args()

    data_str = args.data or date.today().isoformat()
    try:
        datetime.strptime(data_str, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"Data inválida: {data_str!r}, use AAAA-MM-DD")

    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_SERVICE_KEY"]
    resend.api_key = os.environ["RESEND_API_KEY"]
    remetente = os.environ.get("EMAIL_REMETENTE", "alertas@example.com")

    sb = create_client(supabase_url, supabase_key)

    try:
        pdf_bytes = baixa_edicao(data_str)
    except FileNotFoundError as e:
        print(str(e))
        return

    paginas_original = []
    with io.BytesIO(pdf_bytes) as buf, pdfplumber.open(buf) as pdf:
        for page in pdf.pages:
            paginas_original.append(page.extract_text() or "")
    paginas_norm = [normaliza(t) for t in paginas_original]

    termos = carrega_termos_ativos(sb)
    if not termos:
        print("Nenhum termo de busca ativo cadastrado.")
        return

    admins = carrega_admins(sb)
    total_matches = 0

    for termo, pagina, trecho in busca_termos(paginas_norm, paginas_original, termos):
        if ja_notificado(sb, termo["id"], data_str):
            continue  # já notificado numa execução anterior (reprocessamento)

        registra_match(sb, termo, data_str, pagina, trecho)

        dono = termo["users"]
        destinatarios = [dono["email"]] + [a for a in admins if a != dono["email"]]
        envia_email(
            destinatarios=destinatarios,
            nome=dono["nome"],
            termo_valor=termo["valor"],
            pagina=pagina,
            trecho=trecho,
            data_edicao=data_str,
            pdf_bytes=pdf_bytes,
            remetente=remetente,
        )
        total_matches += 1
        print(f"Match: termo={termo['valor']!r} usuario={dono['email']} pagina={pagina}")

    print(f"Concluído. {total_matches} match(es) notificado(s) para a edição de {data_str}.")


if __name__ == "__main__":
    main()
