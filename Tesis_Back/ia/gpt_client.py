import os
from django.conf import settings
from openai import OpenAI, AzureOpenAI

def _client():
    return OpenAI(api_key=settings.OPENAI_API_KEY)

def chat(model: str, messages: list, max_tokens: int, response_format=None, temperature: float = 0.2) -> str:
    client = _client()
    kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if response_format:
        kwargs["response_format"] = response_format  # p.ej. {"type":"json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content
