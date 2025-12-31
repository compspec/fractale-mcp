import os

from langchain_openai import ChatOpenAI

from fractale.core.config import ModelConfig


def create_langchain_model(context: dict):
    """
    Factory to create a LangChain ChatModel based on context/env.
    """
    cfg = ModelConfig.from_context(context)

    # 2. Check for step-specific overrides in context dict directly
    if context.get("llm_provider"):
        cfg.provider = context["llm_provider"]
    if context.get("llm_model"):
        cfg.model_name = context["llm_model"]

    # prevent the Pydantic validation error in LangChain
    if not cfg.model_name:
        if cfg.provider == "gemini":
            cfg.model_name = "gemini-2.5-pro"
        elif cfg.provider == "llama":
            cfg.model_name = "llama3.1"
        else:
            cfg.model_name = "gpt-4o"

    if cfg.provider == "openai" or cfg.provider == "llama":
        # Local/Llama via OpenAI-Compatible
        api_key = cfg.api_key or os.environ.get("OPENAI_API_KEY")

        # Special case for Llama/Ollama local defaults
        if cfg.provider == "llama" and not cfg.base_url:
            cfg.base_url = "http://localhost:11434/v1"
            if not api_key:
                api_key = "ollama"

        return ChatOpenAI(
            model=cfg.model_name, api_key=api_key, base_url=cfg.base_url, temperature=0
        )

    elif cfg.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = (
            cfg.api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        )
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not found.")

        return ChatGoogleGenerativeAI(model=cfg.model_name, google_api_key=api_key, temperature=0)

    raise ValueError(f"LangChain Engine: Provider '{cfg.provider}' not supported.")
