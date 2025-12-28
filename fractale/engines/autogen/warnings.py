import warnings

# This file exists to silence a bunch of loud things.

try:
    from pydantic import PydanticDeprecatedSince20

    warnings.filterwarnings("ignore", category=PydanticDeprecatedSince20)
except ImportError:
    warnings.filterwarnings("ignore", message=".*Support for class-based `config` is deprecated.*")
warnings.filterwarnings(
    "ignore", category=DeprecationWarning, message=".*jsonschema.RefResolver is deprecated.*"
)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=".*Accessing jsonschema.__version__ is deprecated.*",
)
warnings.filterwarnings(
    "ignore", category=DeprecationWarning, message=".*LLMConfig.*syntax is deprecated.*"
)
