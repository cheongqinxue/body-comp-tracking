import base64
import json
import os

from numind.nuextract_utils import convert_json_schema_to_nuextract_template
from openai import AsyncOpenAI

from data_model import BodyCompositionMultipleScan

DEFAULT_OPENAI_API_KEY = "EMPTY"
DEFAULT_OPENAI_BASE_URL = "http://localhost:8000/v1"
DEFAULT_EXTRACT_MODEL = "numind/NuExtract3-W8A8"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
EXTRACT_MODEL_ENV = "EXTRACT_MODEL"


def get_openai_base_url() -> str:
    """Return the configured OpenAI-compatible inference server URL.

    Returns:
        Base URL for chat completions requests.
    """
    return os.getenv(OPENAI_BASE_URL_ENV, DEFAULT_OPENAI_BASE_URL)


def get_extract_model() -> str:
    """Return the configured extraction model name.

    Returns:
        Model identifier passed to the inference server.
    """
    return os.getenv(EXTRACT_MODEL_ENV, DEFAULT_EXTRACT_MODEL)


def is_extraction_connection_error(error: Exception | str) -> bool:
    """Return whether an error indicates the inference server is unreachable.

    Args:
        error: Exception or message raised during extraction.

    Returns:
        True when the configured inference server could not be reached.
    """
    message = str(error).lower()
    return (
        "connection error" in message
        or "connecterror" in message
        or "all connection attempts failed" in message
        or "apiconnectionerror" in message
    )


def extraction_server_help_message(base_url: str | None = None) -> str:
    """Return instructions for starting or configuring the inference server.

    Args:
        base_url: OpenAI-compatible server URL that failed to connect.

    Returns:
        Human-readable troubleshooting instructions.
    """
    resolved_base_url = base_url or get_openai_base_url()
    return (
        f"Could not connect to the extraction server at {resolved_base_url}.\n\n"
        "This app expects an OpenAI-compatible vLLM server, not Unsloth Studio itself. "
        "Start the model with:\n\n"
        "  bash scripts/nuextract3_run\n\n"
        "That serves NuExtract on port 8000 by default. If your server uses another "
        "address, set OPENAI_BASE_URL in .env and restart the app."
    )


class Extractor:
    """Extract body composition scans from images via an OpenAI-compatible server."""

    template, dropped_branches = convert_json_schema_to_nuextract_template(
        BodyCompositionMultipleScan.model_json_schema()
    )

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize the extractor client.

        Args:
            base_url: OpenAI-compatible server URL. Defaults to ``OPENAI_BASE_URL``.
            api_key: API key for the inference server. Defaults to ``OPENAI_API_KEY``.
            model: Model name to request. Defaults to ``EXTRACT_MODEL``.
        """
        self.base_url = base_url or get_openai_base_url()
        self.model = model or get_extract_model()
        self.client = AsyncOpenAI(
            api_key=api_key or os.getenv(OPENAI_API_KEY_ENV, DEFAULT_OPENAI_API_KEY),
            base_url=self.base_url,
        )

    def encode_image(self, image_path: str) -> str:
        """Encode an image file as a base64 data URL.

        Args:
            image_path: Path to the image file.

        Returns:
            Base64 data URL for the image.
        """
        with open(image_path, "rb") as image_file:
            data = base64.b64encode(image_file.read()).decode("utf-8")
        image_base64 = data
        data_url = f"data:image/png;base64,{image_base64}"
        return data_url

    async def extract(self, image_path: str) -> BodyCompositionMultipleScan:
        """Extract body composition scans from an image.

        Args:
            image_path: Path to the image file.

        Returns:
            Extracted body composition scans.
        """
        data_url = self.encode_image(image_path)
        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "image_url", "image_url": {"url": data_url}}],
                }
            ],
            extra_body={
                "chat_template_kwargs": {
                    "template": json.dumps(self.template, indent=4),
                    "enable_thinking": False,
                }
            },
        )
        return BodyCompositionMultipleScan.model_validate_json(
            response.choices[0].message.content  # type: ignore
        )
