// Edge Function chamada por um Database Webhook (Supabase Dashboard >
// Database > Webhooks) configurado para disparar em INSERT na tabela
// `public.users`. Avisa o(s) admin(is) por e-mail sobre o novo cadastro.
//
// Deploy: supabase functions deploy notify-signup
// Secrets necessários (supabase secrets set ...):
//   RESEND_API_KEY, EMAIL_REMETENTE, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

import { createClient } from "npm:@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const payload = await req.json();
  const novoUsuario = payload.record;
  if (!novoUsuario) {
    return new Response("sem record no payload", { status: 400 });
  }

  const sb = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data: admins } = await sb
    .from("users")
    .select("email")
    .eq("is_admin", true)
    .eq("ativo", true);

  const destinatarios = (admins ?? []).map((a) => a.email);
  if (destinatarios.length === 0) {
    return new Response("nenhum admin cadastrado, nada a fazer", { status: 200 });
  }

  await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${Deno.env.get("RESEND_API_KEY")}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: Deno.env.get("EMAIL_REMETENTE"),
      to: destinatarios,
      subject: "Novo cadastro no Alerta Diário Oficial de Santos",
      html: `<p>Novo cadastro:</p>
             <p>Nome: ${novoUsuario.nome}<br>
             E-mail: ${novoUsuario.email}<br>
             Telefone: ${novoUsuario.telefone ?? "-"}</p>`,
    }),
  });

  return new Response("ok", { status: 200 });
});
