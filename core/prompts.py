"""Prompt enhancer (simplified for single-step generation)."""

import aiohttp
from typing import Optional

from ..config import Config
from ..backend.comfy import comfy_client

# Simplified: only use final_render style prompts
_FINAL_PROMPT_PREFIX = (
    "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up, "
    "source_anime, anime style, manga style, Japanese animation, "
    "masterpiece quality, best quality, high quality, highly detailed, "
    "professional lighting, cinematic lighting, dynamic shading, "
    "detailed rendering, vibrant anime colors, clean lines, "
    "beautiful character illustration, trending on Pixiv, "
    "anime key visual, digital anime art, "
)

_FINAL_NEGATIVE = (
    "score_4, score_3, score_2, score_1, score_0, text, watermark, "
    "ugly, worst quality, low quality, normal quality, bad anatomy, "
    "bad hands, missing fingers, extra fingers, extra limbs, "
    "fused fingers, deformed hands, malformed limbs, blurry, grainy, "
    "noisy, pixelated, low resolution, signature, artist name, "
    "western comic, American comic, realistic, photorealistic, "
)

_DEFAULT_NEGATIVE = (
    "score_4, score_3, score_2, score_1, score_0, text, watermark, "
    "ugly, worst quality, low quality, normal quality, bad anatomy, "
    "bad hands, missing fingers, extra fingers, extra limbs, "
    "fused fingers, deformed hands, malformed limbs, blurry, grainy, "
    "noisy, pixelated, low resolution, signature, username, artist name, "
    "text, letters, words, logo, title, caption, date, "
    "western comic style, American comic, realistic, 3d, photorealistic, "
)


class PromptEnhancer:
    """Builds final prompts for single-step generation, with optional Ollama refinement."""

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
        user_input: str,
        persona: Optional[dict] = None,
        refine: bool = True,
    ) -> tuple[str, str]:
        """Build (positive, negative) prompts for final generation.

        Args:
            user_input: The raw user-provided description.
            persona:    Optional persona dict with positive_prompt /
                        negative_prompt keys.
            refine:     Whether to call Ollama for further refinement.

        Returns:
            (positive_prompt, negative_prompt) tuple.
        """
        persona_positive = persona["positive_prompt"] if persona else ""
        persona_negative = persona["negative_prompt"] if persona else _DEFAULT_NEGATIVE

        # Assemble base positive prompt
        parts = [p for p in (_FINAL_PROMPT_PREFIX, persona_positive, user_input) if p]
        positive = ", ".join(parts)
        
        final_negative = f"{_FINAL_NEGATIVE}, {persona_negative}" if persona_negative else _FINAL_NEGATIVE

        if refine:
            positive = await self._refine_with_ollama(positive)

        return positive, final_negative

    # ------------------------------------------------------------------
    # Ollama refinement
    # ------------------------------------------------------------------

    async def _refine_with_ollama(self, prompt: str) -> str:
        """Ask Ollama to enhance the prompt for final generation.

        Falls back to the original prompt if the API call fails.
        """
        system_prompt = (
            "You are an expert Stable Diffusion prompt engineer specializing "
            "in anime illustration. "
            "Improve the following prompt to be more effective for final rendering. "
            "Keep it concise. "
            "Return only the improved tags — no explanations."
            "IMPORTANT: List at least 15 tags for POSITIVE, separated by commas.\n"
        )
        try:
            # Free ComfyUI VRAM so Ollama can load its model
            await comfy_client.unload_models()

            payload = {
                "model": self._ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "keep_alive": 0,
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
            print(f"[prompts] Ollama refinement failed: {exc}")
            return prompt


# Module-level singleton
prompt_enhancer = PromptEnhancer()