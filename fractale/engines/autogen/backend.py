import os

from fractale.core.config import ModelConfig


def get_agent_config(context: dict):
    """
    Constructs the LLM configuration dictionary required by AutoGen agents.
    Adapts Fractale's ModelConfig to AutoGen's specific keys.
    """
    cfg = ModelConfig.from_context(context)

    config_list_entry = {
        "model": cfg.model_name,
        "api_key": cfg.api_key,
    }

    # Gemini is a little different
    if cfg.provider == "openai":
        config_list_entry["api_type"] = "openai"
        # Organization?
        # config_list_entry["organization"] = blaaa

    elif cfg.provider == "llama":
        # AutoGen treats local models as openai type with a custom base_url
        config_list_entry["api_type"] = "openai"
        config_list_entry["base_url"] = cfg.base_url or "http://localhost:11434/v1"

        # Ollama often requires a dummy key if none provided
        if not config_list_entry["api_key"]:
            config_list_entry["api_key"] = "ollama"

    elif cfg.provider == "gemini":
        # pip install pyautogen[gemini]
        config_list_entry["api_type"] = "google"
        cfg.model_name = os.environ.get("GOOGLE_MODEL_NAME") or "gemini-2.5-pro"

    else:
        raise ValueError(f"AutoGen Engine: Provider '{cfg.provider}' not supported.")

    config_list_entry["model"] = cfg.model_name

    # Don't read from disk cache
    llm_config = {
        "config_list": [config_list_entry],
        "cache_seed": None,
        "temperature": 0.0,
        "timeout": 120,
    }
    return llm_config
