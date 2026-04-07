from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
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


def _extract_json(text: str) -> dict:
    """Parse JSON from LLM output, stripping markdown code fences if present."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    return json.loads(cleaned)


def _summarize_one(item: SourceItem) -> SourceItem:
    """Summarize a single item via LLM. Returns the item with populated fields."""
    prompt = (
        "Summarize this source into JSON with three fields:\n"
        "- bullets: 2-3 bullet strings summarizing the key points\n"
        "- why_it_matters: one sentence on relevance to robotics/autonomy practitioners\n"
        "- reflection: a 1-2 sentence first-person thought-provoking reflection from a "
        "technical leader's perspective. Don't restate the summary — add strategic insight: "
        "what this enables, where it falls short, the real question it raises, or what "
        "practitioners should be paying attention to. Be opinionated.\n\n"
        "Avoid precise numbers if uncertain.\n\n"
        f"Title: {item.title}\nURL: {item.url}\nDate: {item.published_at.isoformat()}\n"
        f"Text:\n{item.raw_text_excerpt[:4000]}"
    )
    out = _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a technical leader in robotics and autonomy who writes "
                    "accurate, non-hyped analysis. You blend technical depth with strategic "
                    "thinking. Be concise and output only the requested JSON. "
                    "Respond directly without internal reasoning or <think> blocks."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )
    try:
        parsed = _extract_json(out)
        item.summary_bullets = [str(x) for x in parsed.get("bullets", [])][:3]
        item.why_it_matters = str(parsed.get("why_it_matters", "")).strip()
        item.reflection = str(parsed.get("reflection", "")).strip()
    except Exception:
        item.summary_bullets = ["Key update captured from source."]
        item.why_it_matters = "Potential relevance for simulation, automation, or validation workflows."
        item.reflection = ""
    return item


def summarize_items(items: list[SourceItem]) -> list[SourceItem]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(_summarize_one, items))


def _generate_one(item: SourceItem) -> str:
    """Generate a single LinkedIn post draft via LLM."""
    reflection_ctx = ""
    if item.reflection:
        reflection_ctx = f"\nReflection (first-person insight): {item.reflection}"

    prompt = (
        "Write a single LinkedIn post draft in markdown for this robotics/autonomy article. "
        "Include the source link. Be accurate, non-hyped, and concise (2-4 sentences + hashtags). "
        "Include a 'My take:' paragraph — a first-person, opinionated reflection from a "
        "technical leader. It should be thought-provoking, not a restatement of the summary.\n\n"
        f"Title: {item.title}\n"
        f"URL: {item.url}\n"
        f"Key points: {'; '.join(item.summary_bullets)}\n"
        f"Why it matters: {item.why_it_matters}"
        f"{reflection_ctx}"
    )
    return _call_llm(
        [
            {
                "role": "system",
                "content": (
                    "You are a technical leader in robotics and autonomy who writes "
                    "accurate, non-hyped LinkedIn posts. You blend technical depth with "
                    "strategic thinking. Respond directly without internal reasoning "
                    "or <think> blocks."
                ),
            },
            {"role": "user", "content": prompt},
        ]
    )


def generate_posts(items: list[SourceItem], max_posts: int = 3) -> str:
    with ThreadPoolExecutor(max_workers=4) as pool:
        drafts = list(pool.map(_generate_one, items[:max_posts]))
    return "\n\n---\n\n".join(drafts)
