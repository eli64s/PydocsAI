"""OpenAI API handler for generating text for the README.md file."""

import asyncio
import os
from typing import Dict, Tuple

import httpx
import openai
from cachetools import TTLCache

from logger import Logger
from utils import format_sentence

LOGGER = Logger("readmeai_logger")
ENGINE = "text-davinci-003"
MAX_TOKENS = 4096
TOKENS = 500
TEMPERATURE = 0.7


class OpenAIError(Exception):
    """Custom exception for OpenAI API errors."""


def get_cache():
    """Get a TTLCache for storing OpenAI API responses."""
    # Add TTLCache with a maximum size of 500 items and 600 seconds of TTL.
    return TTLCache(maxsize=500, ttl=600)


def get_http_client():
    """Get an HTTP client with the appropriate settings."""
    return httpx.AsyncClient(
        http2=True,
        timeout=30,
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=100),
    )


async def code_to_text(
    ignore_files: list, files: Dict[str, str], prompt: str
) -> Dict[str, str]:
    """Generate summary text for each file in the repository using OpenAI's GPT-3.

    Parameters
    ----------
    ignore_files
        Files to ignore in the repository when generating summaries.
    files
        Hashmap of file paths and their contents.
    prompt
        Prompt to send to OpenAI's GPT API i.e. the code to summarize.

    Returns
    -------
        Hashmap of file paths and their summaries generated.
    """
    http_client = get_http_client()
    cache = get_cache()

    tasks = []

    for path, contents in files.items():
        if any(fn in str(path) for fn in ignore_files):
            LOGGER.debug(f"Skipping file: {path}")
            continue

        prompt_code = prompt.format(contents)
        prompt_len = len(prompt_code.split())

        if prompt_len > MAX_TOKENS:
            err = "Prompt exceeds max token limit: {}"
            tasks.append(
                asyncio.create_task(null_summary(path, err.format(prompt_len)))
            )
            LOGGER.debug(err.format(prompt_code))
            continue

        tasks.append(
            asyncio.create_task(
                fetch_summary(path, prompt_code, http_client, cache)
            )
        )

    results = await asyncio.gather(*tasks)

    return results


async def fetch_summary(
    file: str, prompt: str, http_client, cache
) -> Tuple[str, str]:
    """Generate summary text for a given file path using OpenAI's GPT-3 API.

    Parameters
    ----------
    file
        File path for which to fetch summary text.
    prompt
        Prompt to send to OpenAI's GPT API i.e. the code to summarize.
    http_client
        HTTP client to use for making requests to the OpenAI API.
    cache
        Local cache to store OpenAI API responses.

    Returns
    -------
        Tuple containing the file path and the generated summary text.

    Raises
    ------
    OpenAIError
        If the OpenAI API response is missing the 'choices' field.
    """
    if prompt in cache:
        LOGGER.debug(f"Using cached summary for {file}")
        return (file, cache[prompt])

    try:
        LOGGER.info(f"Davinci processing: {file}")

        response = await http_client.post(
            f"https://api.openai.com/v1/engines/{ENGINE}/completions",
            json={
                "prompt": prompt,
                "temperature": TEMPERATURE,
                "max_tokens": TOKENS,
                "top_p": 1,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
            },
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
        )

        if response.status_code != 200:
            LOGGER.error(f"Error fetching summary for {file}: {response.text}")
            return (file, "Error generating file summary.")

        response.raise_for_status()
        data = response.json()

        if "choices" not in data or len(data["choices"]) == 0:
            raise OpenAIError("OpenAI response missing 'choices' field.")

        summary = data["choices"][0]["text"]
        summary = format_sentence(summary)
        cache[prompt] = summary

        return (file, summary)

    except Exception as e:
        LOGGER.error(f"Error fetching summary for {file}: {str(e)}")
        return (file, "Error generating file summary.")


def generate_summary_text(prompt: str) -> str:
    """
    Prompts the OpenAI large language model API to
    generate summaries for each file in the repository.

    Parameters
    ----------
    prompt : str
        The prompt to send to OpenAI's GPT API.

    Returns
    -------
    str
        Text generated by OpenAI's GPT API.
    """
    completions = openai.Completion.create(
        engine=ENGINE,
        prompt=prompt,
        max_tokens=TOKENS,
        temperature=TEMPERATURE,
    )
    generated_text = completions.choices[0].text

    return generated_text.lstrip().strip('"')


async def null_summary(file: str, summary: str) -> Tuple[str, str]:
    """Placeholder summary for files that exceed the max token limit."""
    return (file, summary)
