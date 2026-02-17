from __future__ import annotations

import json
import os
from typing import Any

import requests

from .models import SourceItem


def _call_llm(input_messages: list[dict[str, Any]]) -> str:
    """Call LLM API (OpenAI or local model with OpenAI-compatible API)"""

    # Get provider selection - REQUIRED, no defaults
    provider = os.environ.get("LLM_PROVIDER")
    if not provider:
        raise RuntimeError(
            "LLM_PROVIDER is not set in .env file!\n"
            "Please set LLM_PROVIDER to either 'openai' or 'local'"
        )

    provider = provider.lower()

    if provider == "local":
        # Local model configuration - all required
        model = os.environ.get("LOCAL_MODEL")
        if not model:
            raise RuntimeError(
                "LOCAL_MODEL is not set in .env file!\n"
                "Please set LOCAL_MODEL (e.g., 'llama3.2', 'mistral', etc.)"
            )

        base_url = os.environ.get("LOCAL_BASE_URL")
        if not base_url:
            raise RuntimeError(
                "LOCAL_BASE_URL is not set in .env file!\n"
                "Please set LOCAL_BASE_URL (e.g., 'http://localhost:11434/v1' for Ollama)"
            )

        api_key = os.environ.get("LOCAL_API_KEY", "not-needed")
        endpoint = f"{base_url.rstrip('/')}/chat/completions"

    elif provider == "openai":
        # OpenAI configuration - all required
        model = os.environ.get("OPENAI_MODEL")
        if not model:
            raise RuntimeError(
                "OPENAI_MODEL is not set in .env file!\n"
                "Please set OPENAI_MODEL (e.g., 'gpt-4o-mini', 'gpt-4o', etc.)"
            )

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set in .env file!\n"
                "Get your key from: https://platform.openai.com/api-keys"
            )

        base_url = "https://api.openai.com/v1"
        endpoint = f"{base_url}/chat/completions"

    else:
        raise RuntimeError(
            f"Invalid LLM_PROVIDER '{provider}' in .env file!\n"
            "LLM_PROVIDER must be either 'openai' or 'local'"
        )

    # Standard OpenAI-compatible payload
    payload = {
        "model": model,
        "messages": input_messages,
        "temperature": 0.7,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # Get timeout from env or use default
    timeout = int(os.environ.get("LLM_TIMEOUT", "120"))

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Failed to connect to LLM server at {endpoint}\n"
            f"Provider: {provider}, Model: {model}\n"
            f"Error: {e}\n"
            f"Hint: Make sure your {provider} server is running!"
        ) from e
    except requests.exceptions.Timeout as e:
        raise RuntimeError(
            f"LLM request timed out after {timeout} seconds\n"
            f"Provider: {provider}, Model: {model}\n"
            f"Hint: Try a faster model or increase LLM_TIMEOUT in .env"
        ) from e
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"LLM API returned error: {response.status_code}\n"
            f"Provider: {provider}, Model: {model}\n"
            f"Response: {response.text}\n"
            f"Hint: Check your API key and model name"
        ) from e

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, ValueError) as e:
        raise RuntimeError(
            f"Unexpected response format from LLM API\n"
            f"Provider: {provider}, Model: {model}\n"
            f"Response: {response.text[:500]}\n"
            f"Error: {e}"
        ) from e


def summarize_items(items: list[SourceItem]) -> list[SourceItem]:
    summarized: list[SourceItem] = []
    for item in items:
        prompt = (
            "Summarize this source into JSON with fields bullets (2-3 bullet strings) and why_it_matters (string). "
            "Avoid precise numbers if uncertain.\n\n"
            f"Title: {item.title}\nURL: {item.url}\nDate: {item.published_at.isoformat()}\n"
            f"Text:\n{item.raw_text_excerpt[:4000]}"
        )
        out = _call_llm(
            [
                {
                    "role": "system",
                    "content": "You are a technical writer for autonomy & robotics. Write accurate, non-hyped summaries. Be concise and output only the requested JSON. Respond directly without internal reasoning or <think> blocks.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        try:
            parsed = json.loads(out)
            item.summary_bullets = [str(x) for x in parsed.get("bullets", [])][:3]
            item.why_it_matters = str(parsed.get("why_it_matters", "")).strip()
        except Exception:
            item.summary_bullets = ["Key update captured from source."]
            item.why_it_matters = "Potential relevance for simulation, automation, or validation workflows."
        summarized.append(item)
    return summarized


def generate_posts(items: list[SourceItem], max_posts: int = 3) -> str:
    serial = []
    for i, item in enumerate(items, start=1):
        serial.append(
            {
                "idx": i,
                "title": item.title,
                "url": item.url,
                "date": item.published_at.date().isoformat(),
                "bullets": item.summary_bullets,
                "why_it_matters": item.why_it_matters,
            }
        )

    prompt = (
        f"Create {max_posts} LinkedIn-style social media post drafts in markdown. "
        "Focus on autonomy + robotics with strong relevance to simulation, automation, validation. "
        "Include source links in each draft. Avoid hype and avoid precise numeric claims when uncertain. "
        "Separate each draft with '\n\n---\n\n'.\n"
        f"Sources:\n{json.dumps(serial, indent=2)}"
    )
    return _call_llm(
        [
            {
                "role": "system",
                "content": "You are a technical writer for autonomy & robotics. Write accurate, non-hyped posts. Respond directly without internal reasoning or <think> blocks.",
            },
            {"role": "user", "content": prompt},
        ]
    )
