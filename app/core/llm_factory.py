from __future__ import annotations
from functools import lru_cache
from typing import Any
from langchain_core.language_models import BaseChatModel
from loguru import logger
from app.core.settings import get_settings

@lru_cache(maxsize=1)
def get_llm() -> BaseChatModel:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    logger.info(
        "Inizializzazione LLM",
        provider=provider,
        model=settings.llm_model,
    )
    if provider == "ollama":
        return _build_ollama(settings)
    elif provider == "openai":
        return _build_openai(settings)
    elif provider == "google":
        return _build_google(settings)
    else:
        raise ValueError(
            f"Provider LLM '{provider}' non supportato.\n Usa: ollama | openai | google "
        )

def _build_ollama(settings: Any) -> BaseChatModel:
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        raise ImportError(
            "Installa langchain-ollama per usare Ollama come provider:  pip install langchain-ollama"
        )
    return ChatOllama(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
        num_ctx=settings.llm_num_ctx,
        num_predict=settings.llm_max_tokens,
        timeout=settings.llm_timeout,
    )

def _build_openai(settings: Any) -> BaseChatModel:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "Installa langchain-openai per usare OpenAI come provider:  pip install langchain-openai"
        )
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY mancante nel .env")
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.openai_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout,
        streaming=settings.llm_streaming,
    )

def _build_google(settings: Any) -> BaseChatModel:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError(
            "Installa langchain-google-genai per usare Google come provider:  pip install langchain-google-genai"
        )
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY mancante nel .env")
    return ChatGoogleGenerativeAI(
        model=settings.llm_model,
        google_api_key=settings.google_api_key,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_tokens,
    )

def get_llm_for_tenant(
    tenant_settings: dict | None = None,
) -> BaseChatModel:
    if not tenant_settings:
        return get_llm()
    settings = get_settings()
    provider = tenant_settings.get("provider", settings.llm_provider).lower()
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=tenant_settings.get("model", settings.llm_model),
            api_key=tenant_settings.get("api_key", settings.openai_api_key),
            temperature=tenant_settings.get("temperature", settings.llm_temperature),
            max_tokens=settings.llm_max_tokens,
            streaming=settings.llm_streaming,
        )

    return get_llm()

