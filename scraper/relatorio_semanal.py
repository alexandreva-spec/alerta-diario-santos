"""
Relatório semanal para o(s) administrador(es) do Alerta Diário Oficial de Santos.

Roda uma vez por semana (ver ../.github/workflows/semanal.yml) e envia por
e-mail para os admins:
- lista de todos os cadastrados até hoje
- lista dos alertas (matches) gerados nos últimos 7 dias
- um gráfico de cadastros novos x alertas gerados, dia a dia, na semana

Variáveis de ambiente esperadas:
  SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY, EMAIL_REMETENTE
"""

import base64
import io
import os
from datetime import date, datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import resend
from supabase import Client, create_client


def carrega_usuarios(sb: Client) -> list[dict]:
    resp = sb.table("users").select("nome, email, ativo, created_at").order("created_at").execute()
    return resp.data or []


def carrega_admins(sb: Client) -> list[str]:
    resp = sb.table("users").select("email").eq("is_admin", True).eq("ativo", True).execute()
    return [r["email"] for r in (resp.data or [])]


def carrega_matches_semana(sb: Client, desde_iso: str) -> list[dict]:
    resp = (
        sb.table("matches")
        .select("data_edicao, pagina, created_at, users(nome), search_terms(valor)")
        .gte("created_at", desde_iso)
        .order("created_at")
        .execute()
    )
    return resp.data or []


def _para_data(timestamp_iso: str) -> date:
    return datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00")).date()


def monta_grafico(usuarios: list[dict], matches: list[dict], dias: list[date]) -> bytes:
    cadastros_por_dia = {d: 0 for d in dias}
    for u in usuarios:
        d = _para_data(u["created_at"])
        if d in cadastros_por_dia:
            cadastros_por_dia[d] += 1

    alertas_por_dia = {d: 0 for d in dias}
    for m in matches:
        d = _para_data(m["created_at"])
        if d in alertas_por_dia:
            alertas_por_dia[d] += 1

    labels = [d.strftime("%d/%m") for d in dias]
    posicoes = range(len(dias))
    largura = 0.35

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(
        [i - largura / 2 for i in posicoes],
        [cadastros_por_dia[d] for d in dias],
        largura,
        label="Novos cadastros",
        color="#2f6b4f",
    )
    ax.bar(
        [i + largura / 2 for i in posicoes],
        [alertas_por_dia[d] for d in dias],
        largura,
        label="Alertas gerados",
        color="#a4453a",
    )
    ax.set_xticks(list(posicoes))
    ax.set_xticklabels(labels)
    ax.set_title("Cadastros novos x alertas gerados (últimos 7 dias)")
    ax.legend()
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


def monta_tabela_usuarios(usuarios: list[dict]) -> str:
    linhas = "".join(
        f"<tr><td>{u['nome']}</td><td>{u['email']}</td>"
        f"<td>{'ativo' if u['ativo'] else 'pausado'}</td>"
        f"<td>{u['created_at'][:10]}</td></tr>"
        for u in usuarios
    )
    return f"""
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
      <tr style="background:#eee;"><th>Nome</th><th>E-mail</th><th>Status</th><th>Cadastrado em</th></tr>
      {linhas or '<tr><td colspan="4">Nenhum cadastrado ainda.</td></tr>'}
    </table>
    """


def monta_tabela_matches(matches: list[dict]) -> str:
    linhas = "".join(
        f"<tr><td>{m['users']['nome']}</td>"
        f"<td>{m['search_terms']['valor']}</td>"
        f"<td>{m['data_edicao']}</td><td>{m['pagina']}</td></tr>"
        for m in matches
    )
    return f"""
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-size:13px;">
      <tr style="background:#eee;"><th>Pessoa</th><th>Termo</th><th>Edição</th><th>Página</th></tr>
      {linhas or '<tr><td colspan="4">Nenhum alerta nos últimos 7 dias.</td></tr>'}
    </table>
    """


def main():
    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_SERVICE_KEY"]
    resend.api_key = os.environ["RESEND_API_KEY"]
    remetente = os.environ.get("EMAIL_REMETENTE", "alertas@example.com")

    sb = create_client(supabase_url, supabase_key)

    admins = carrega_admins(sb)
    if not admins:
        print("Nenhum admin cadastrado, nada a enviar.")
        return

    hoje = date.today()
    dias = [hoje - timedelta(days=i) for i in range(6, -1, -1)]
    desde_iso = datetime.combine(dias[0], datetime.min.time()).isoformat()

    usuarios = carrega_usuarios(sb)
    matches = carrega_matches_semana(sb, desde_iso)
    grafico_png = monta_grafico(usuarios, matches, dias)

    total_ativos = sum(1 for u in usuarios if u["ativo"])
    corpo = f"""
    <p>Relatório semanal do Alerta Diário Oficial de Santos &mdash; {hoje.strftime('%d/%m/%Y')}.</p>
    <p><b>{len(usuarios)}</b> pessoas cadastradas no total ({total_ativos} ativas) &middot;
    <b>{len(matches)}</b> alertas gerados nos últimos 7 dias.</p>
    <p>O gráfico com cadastros novos x alertas por dia está anexado.</p>
    <h3>Cadastrados</h3>
    {monta_tabela_usuarios(usuarios)}
    <h3>Alertas dos últimos 7 dias</h3>
    {monta_tabela_matches(matches)}
    """

    resend.Emails.send(
        {
            "from": remetente,
            "to": admins,
            "subject": f"[Alerta DO Santos] Relatório semanal — {hoje.strftime('%d/%m/%Y')}",
            "html": corpo,
            "attachments": [
                {
                    "filename": f"grafico_semanal_{hoje.isoformat()}.png",
                    "content": list(base64.b64encode(grafico_png)),
                }
            ],
        }
    )
    print(f"Relatório semanal enviado para {', '.join(admins)}.")


if __name__ == "__main__":
    main()
