from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Any
import yaml
from loguru import logger

def get_rag_system_prompt(tenant_name: str = "Compet-e Compliance AI") -> str:
    prompts = _load_prompts()
    template = prompts.get("system", {}).get("base", _DEFAULT_SYSTEM)
    return template.format( tenant_name=tenant_name )

def get_rag_user_prompt(
    context: str,
    history: str,
    question: str,
) -> str:
    prompts = _load_prompts()
    template = prompts.get("rag", {}).get("main", _DEFAULT_RAG)
    return template.format(
        context=context,
        history=history,
        question=question,
    )

def get_no_context_message() -> str:
    prompts = _load_prompts()
    return prompts.get("rag", {}).get("no_context", _DEFAULT_NO_CONTEXT)

@lru_cache(maxsize=1)
def _load_prompts() -> dict:
    prompt_file = Path("/app/config/prompts.yaml")
    if not prompt_file.exists():
        logger.warning("prompts.yaml non trovato, uso prompt hardcodati")
        return {}
    with open(prompt_file) as f:
        return yaml.safe_load(f) or {}

_DEFAULT_SYSTEM = """Sei un assistente legale AI per {tenant_name}.
Rispondi sempre in italiano a meno che l'utente non scriva in un'altra lingua.
Sei preciso, professionale e citi sempre le fonti dei documenti.
Non inventare mai informazioni che non sono nei documenti forniti.
Se non trovi la risposta nei documenti, dillo esplicitamente."""

_DEFAULT_RAG = """Usa ESCLUSIVAMENTE le seguenti sezioni di documenti per rispondere.
Per ogni informazione, cita il documento nel formato [Fonte: nome_file, p.X].
Se la risposta non è nei documenti, dì: "Non ho trovato questa informazione nei documenti."

DOCUMENTI:
{context}

STORICO CONVERSAZIONE:
{history}

DOMANDA: {question}

RISPOSTA:"""

_DEFAULT_NO_CONTEXT = ("Non ho trovato documenti rilevanti per rispondere. "  "Prova a riformulare la domanda o carica i documenti pertinenti.")
