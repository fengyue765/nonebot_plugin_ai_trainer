"""Prompt enhancer.

Generates step-specific prompts for the 4-stage painting pipeline
(sketch → lineart → flat_color → final_render).

Combines user input, the active persona's style, and step-specific
prefixes. Optionally calls Ollama to further refine the prompt.
"""

import aiohttp
from typing import Optional

from ..config import Config

# Step-specific prefix templates injected before the user's subject
_STEP_PREFIXES: dict[str, str] = {
    "sketch": (
        "rough pencil sketch, simple pose composition, basic shapes, "
        "gesture lines, minimal detail, "
    ),
    "lineart": (
        "clean ink lineart, precise lines, no color, high detail linework, "
    ),
    "flat_color": (
        "flat base colors, large color blocks, anime flat shading, "
        "simple coloring, "
    ),
    "final_render": (
        "masterpiece quality, lighting and shadows, highlights, rim light, "
        "soft gradients, polished rendering, "
    ),
}

_DEFAULT_NEGATIVE = "lowres, blurry, bad anatomy, worst quality, extra limbs"


class PromptEnhancer:
    """Builds prompts for each pipeline step, with optional Ollama refinement."""

    def __init__(
        self,
        ollama_url: str = Config.OLLAMA_URL,
        ollama_model: str = Config.OLLAMA_MODEL,
    ) -> None:
        self._ollama_url = ollama_url.rstrip("/")
        self._ollama_model = ollama_model

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def build_prompt(
        self,
        step: str,
        user_input: str,
        persona: Optional[dict] = None,
        refine: bool = True,
    ) -> tuple[str, str]:
        """Build (positive, negative) prompts for a given pipeline step.

        Args:
            step:       One of the PIPELINE_STEPS keys (e.g. "sketch").
            user_input: The raw user-provided description.
            persona:    Optional persona dict with positive_prompt /
                        negative_prompt keys.
            refine:     Whether to call Ollama for further refinement.

        Returns:
            (positive_prompt, negative_prompt) tuple.
        """
        prefix = _STEP_PREFIXES.get(step, "")
        persona_positive = persona["positive_prompt"] if persona else ""
        persona_negative = persona["negative_prompt"] if persona else _DEFAULT_NEGATIVE

        # Assemble base positive prompt
        parts = [p for p in (prefix, persona_positive, user_input) if p]
        positive = ", ".join(parts)
        negative = persona_negative or _DEFAULT_NEGATIVE

        if refine:
            positive = await self._refine_with_ollama(step, positive)

        return positive, negative

    # ------------------------------------------------------------------
    # Ollama refinement
    # ------------------------------------------------------------------

    async def _refine_with_ollama(self, step: str, prompt: str) -> str:
        """Ask Ollama to enhance the prompt for the given step.

        Falls back to the original prompt if the API call fails.
        """
        system_prompt = (
            "You are an expert Stable Diffusion prompt engineer specializing "
            "in anime illustration. "
            f"The current pipeline step is: {step}. "
            "Improve the following prompt to be more effective for this step. "
            "Keep it concise (under 100 words). "
            "Return only the improved prompt — no explanations."
        )
        try:
            payload = {
                "model": self._ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._ollama_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=Config.OLLAMA_TIMEOUT),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    refined: str = data["message"]["content"].strip()
                    return refined if refined else prompt
        except Exception as exc:
            print(f"[prompts] Ollama refinement failed for step '{step}': {exc}")
            return prompt


# Module-level singleton
prompt_enhancer = PromptEnhancer()
