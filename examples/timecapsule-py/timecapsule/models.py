"""Curated OpenRouter models and terminal-friendly selection."""

from __future__ import annotations

from dataclasses import dataclass
import getpass
import os
import sys


@dataclass(frozen=True)
class ModelOption:
    model_id: str
    label: str
    free: bool


# These are intentionally small and reviewed against OpenRouter's live model
# catalogue. The free entries are also the only automatic failover targets.
TESTED_MODELS = (
    ModelOption("google/gemma-4-31b-it:free", "Google Gemma 4 31B", True),
    ModelOption("liquid/lfm-2.5-2.6b:free", "Liquid LFM2.5 2.6B", True),
    ModelOption("minimax/minimax-m3:free", "MiniMax M3", True),
    ModelOption("openai/gpt-5.4-mini", "OpenAI GPT-5.4 Mini", False),
    ModelOption("anthropic/claude-haiku-4.5", "Anthropic Claude Haiku 4.5", False),
)
TESTED_MODELS_BY_ID = {option.model_id: option for option in TESTED_MODELS}
FREE_MODEL_IDS = tuple(option.model_id for option in TESTED_MODELS if option.free)


def model_options() -> tuple[ModelOption, ...]:
    return TESTED_MODELS


def select_model(requested: str | None = None, allow_untested: bool = False) -> ModelOption:
    """Resolve --model or show a numbered interactive model picker."""
    if requested:
        option = TESTED_MODELS_BY_ID.get(requested)
        if option:
            return option
        if allow_untested:
            return ModelOption(requested, requested, requested.endswith(":free"))
        supported = ", ".join(TESTED_MODELS_BY_ID)
        raise SystemExit(
            f"Model '{requested}' is not in the tested catalogue. "
            f"Use --allow-untested-model to override. Tested models: {supported}"
        )

    if not sys.stdin.isatty():
        raise SystemExit("Model selection needs a terminal; pass --model MODEL_ID in non-interactive mode.")

    print("\nOpenRouter model\n")
    for index, option in enumerate(TESTED_MODELS, start=1):
        price = "FREE" if option.free else "PAID"
        print(f"  {index}. {price:<4} · {option.label}  ({option.model_id})")
    print("\nFree models are tried in order if a free route is rate limited.")
    while True:
        try:
            value = input(f"\nSelect a model [1-{len(TESTED_MODELS)}] (default 1): ").strip()
        except EOFError as error:
            raise SystemExit("No model selected. Pass --model MODEL_ID to run non-interactively.") from error
        if not value:
            return TESTED_MODELS[0]
        if value.isdigit() and 1 <= int(value) <= len(TESTED_MODELS):
            return TESTED_MODELS[int(value) - 1]
        print(f"Choose a number from 1 to {len(TESTED_MODELS)}.")


def openrouter_api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    if not sys.stdin.isatty():
        raise SystemExit(
            "OPENROUTER_API_KEY not detected. Set it in the environment or run model mode from a terminal."
        )
    try:
        key = getpass.getpass("OpenRouter API key not detected. Enter API key: ").strip()
    except EOFError as error:
        raise SystemExit("No OpenRouter API key entered.") from error
    if not key:
        raise SystemExit("No OpenRouter API key entered.")
    return key
