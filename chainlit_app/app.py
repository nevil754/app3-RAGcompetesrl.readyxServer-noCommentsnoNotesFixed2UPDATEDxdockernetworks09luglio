from __future__ import annotations
import json
import os
import httpx
import chainlit as cl

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")
DEFAULT_TENANT = os.getenv("CHAINLIT_DEFAULT_TENANT", "demo-corp")

@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    email = username
    tenant_slug = DEFAULT_TENANT
    if "|" in username:
        email, tenant_slug = username.split("|", 1)
        email = email.strip()
        tenant_slug = tenant_slug.strip()
    try:
        async with httpx.AsyncClient( timeout=10.0 ) as client:
            resp = await client.post(
                f"{FASTAPI_URL}/api/v1/auth/login",
                json={"email": email, "password": password, "tenant_slug": tenant_slug},
            )
        if resp.status_code == 200:
            data = resp.json()
            return cl.User(
                identifier=email,
                metadata={
                    "access_token": data["access_token"],
                    "user_role": data.get("user_role", "user"),
                    "user_id": data.get("user_id", ""),
                    "tenant_slug": data.get("tenant_slug", tenant_slug),
                },
            )
    except Exception:
        pass
    return None

@cl.on_chat_start
async def on_chat_start() -> None:
    user: cl.User = cl.user_session.get("user")
    tenant = user.metadata.get("tenant_slug", DEFAULT_TENANT)
    role = user.metadata.get("user_role", "user")
    cl.user_session.set("conversation_id", None)
    await cl.Message(
        content=(
            f"Benvenuto nel sistema **RAG Enterprise Compet-e**!\n\n"
            f"Tenant: `{tenant}` | Ruolo: `{role}`\n\n"
            "Poni una domanda sui documenti caricati nel sistema. "
            "Uso retrieval semantico ibrido (dense + sparse) + reranking per trovare le risposte più precise."
        ),
    ).send()

@cl.on_message
async def on_message(message: cl.Message) -> None:
    user: cl.User = cl.user_session.get("user")
    access_token: str = user.metadata.get("access_token", "")
    conversation_id: str | None = cl.user_session.get("conversation_id")
    answer_msg = cl.Message(content="")
    await answer_msg.send()
    meta: dict = {}
    try:
        timeout = httpx.Timeout(120.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{FASTAPI_URL}/api/v1/chat/stream",
                json={
                    "question": message.content,
                    "conversation_id": conversation_id,
                },
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "text/event-stream",
                },
            ) as resp:
                if resp.status_code == 401:
                    await answer_msg.update(
                        content="Sessione scaduta. Ricarica la pagina ed esegui nuovamente il login."
                    )
                    return
                if resp.status_code != 200:
                    await answer_msg.update(
                        content=f"Errore backend: HTTP {resp.status_code}. Riprova tra qualche istante."
                    )
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:]
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if "token" in payload:
                        await answer_msg.stream_token( payload["token"] )
                    elif payload.get("done"):
                        meta = payload
                    elif "error" in payload:
                        await answer_msg.stream_token( f"\n\nErrore: {payload['error']}" )

    except httpx.ReadTimeout:
        await answer_msg.stream_token(
            "\n\nTimeout: il modello ha impiegato troppo tempo a rispondere."
        )
    except Exception as exc:
        await answer_msg.stream_token( f"\n\nErrore imprevisto: {exc}" )
    await answer_msg.update()
    new_conv_id = meta.get("conversation_id")
    if new_conv_id:
        cl.user_session.set("conversation_id", new_conv_id)

    sources: list[dict] = meta.get("sources", [])
    if not sources:
        return
    elements: list[cl.Text] = []
    lines: list[str] = ["**Fonti utilizzate:**"]
    for i, src in enumerate(sources, 1):
        fname = src.get("filename", "—")
        page = src.get("page_number")
        score = src.get("score", 0.0)
        snippet = src.get("snippet", "")
        label = f"[{i}] {fname}"
        if page:
            label += f" — p. {page}"
        label += f"  `score: {score:.3f}`"

        lines.append(label)
        if snippet:
            elements.append(
                cl.Text(
                    name=f"Fonte {i} — {fname}",
                    content=snippet,
                    display="side",
                )
            )
    await cl.Message(
        content="\n".join(lines),
        elements=elements,
    ).send()

