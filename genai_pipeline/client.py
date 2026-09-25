"""Pipeline 1 - connection to the Generative AI API.
Two providers are supported: OpenAI and Google Gemini. Choose one with GENAI_PROVIDER in .env.
Only this file talks to the external API, so the provider can be swapped in one place.
Every client has the same method:  generate(system, prompt, temperature) -> JSON text."""
from flask import current_app


class GenAIError(Exception):
    pass


class GeminiClient:
    def __init__(self, api_key, model):
        if not api_key:
            raise GenAIError("GEMINI_API_KEY is not configured in the .env file.")
        from google import genai
        self._genai = genai
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(self, system, prompt, temperature):
        from google.genai import types
        try:
            resp = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config=types.GenerateContentConfig(system_instruction=system, temperature=temperature, max_output_tokens=32768,
                                                   response_mime_type="application/json"))
        except Exception as e:                        # timeout, quota, network, invalid key ...
            raise GenAIError(f"{e.__class__.__name__}: {str(e)[:300]}")
        text = getattr(resp, "text", None)
        if not text:
            raise GenAIError("The API returned an empty response (possibly blocked or truncated).")
        return text


class OpenAIClient:
    def __init__(self, api_key, model, timeout=180):
        if not api_key:
            raise GenAIError("OPENAI_API_KEY is not configured in the .env file.")
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=0)   # our own retry logic is used
        self.model = model

    def _uses_fixed_temperature(self):
        # GPT-5 / GPT-6 and o-series reasoning models only accept their default temperature
        return self.model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))

    def generate(self, system, prompt, temperature):
        args = {"model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"}}     # forces a single valid JSON object
        if not self._uses_fixed_temperature():
            args["temperature"] = temperature
        try:
            resp = self.client.chat.completions.create(**args)
        except Exception as e:                            # invalid key, quota, timeout, unknown model ...
            raise GenAIError(f"{e.__class__.__name__}: {str(e)[:300]}")
        choice = resp.choices[0]
        text = choice.message.content
        if choice.finish_reason == "length":
            raise GenAIError("The response was cut off (output too long). Try again or reduce the number of modules.")
        if not text:
            raise GenAIError("The API returned an empty response (possibly refused or filtered).")
        return text


_override = None


def set_client_override(client):
    """Used only by automated tests to plug in a local stand-in for the API."""
    global _override
    _override = client


def get_client():
    if _override is not None:
        return _override
    cfg = current_app.config
    provider = cfg.get("GENAI_PROVIDER", "openai")
    if provider == "openai":
        return OpenAIClient(cfg["OPENAI_API_KEY"], cfg["OPENAI_MODEL"], cfg.get("GENAI_TIMEOUT_SECONDS", 180))
    if provider == "gemini":
        return GeminiClient(cfg["GEMINI_API_KEY"], cfg["GEMINI_MODEL"])
    raise GenAIError(f"Unknown GENAI_PROVIDER '{provider}'. Use 'openai' or 'gemini'.")


def model_name():
    return getattr(get_client(), "model", "unknown")
