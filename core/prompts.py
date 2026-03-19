"""Prompt enhancer.

Generates step-specific prompts for the 4-stage painting pipeline
(sketch → lineart → flat_color → final_render).

Combines user input, the active persona's style, and step-specific
prefixes. Optionally calls Ollama to further refine the prompt.
"""

import aiohttp
from typing import Optional

from ..config import Config
from ..backend.comfy import comfy_client

# Step-specific prefix templates injected before the user's subject
_STEP_PREFIXES: dict[str, str] = {
    "sketch": (
        "anime rough sketch, manga draft, Japanese animation style sketch, "
        "simple clean construction lines, rough pose sketch, basic shapes, "
        "light construction lines, quick gesture sketch, minimal detail, "
        "black and white, white background, hand-drawn anime style, "
        "shojo manga sketch, shonen manga rough draft, "
        "anime character draft, rough composition sketch, "
        "no shading, no rendering, "
    ),
    
    "lineart": (
        "anime clean lineart, manga ink lines, Japanese animation lineart, "
        "crisp clean lines, precise ink work, professional line weight, "
        "black lines on white, celtic lines, sharp outlines, "
        "no color, no shading, no grayscale, clean line art, "
        "manga style linework, anime illustration lines, "
        "contour lines, varied line thickness, "
    ),
    
    "flat_color": (
        "anime flat colors, manga style coloring, Japanese animation colors, "
        "cel shading, base colors, solid color blocks, flat shading, "
        "anime style color fill, simple shading, no gradients, "
        "clean color separation, vector flat style, graphic style, "
        "bright anime colors, character design colors, "
    ),
    
    "final_render": (
        "score_9, score_8_up, score_7_up, score_6_up, score_5_up, score_4_up, "
        "source_anime, anime style, manga style, Japanese animation, "
        "masterpiece quality, best quality, high quality, highly detailed, "
        "professional lighting, cinematic lighting, dynamic shading, "
        "detailed rendering, vibrant anime colors, clean lines, "
        "beautiful character illustration, trending on Pixiv, "
        "anime key visual, digital anime art, "
    ),
}

_STEP_NEGATIVES: dict[str, str] = {
    "sketch": (
        "western comic style, American comic, Marvel, DC, realistic, "
        "detailed rendering, shading, shadows, lighting, colors, painting, "
        "3d, photorealistic, intricate, polished, finished, "
        "background, complex, ornate, "
    ),
    
    "lineart": (
        "western comic, American manga, realistic, shading, shadows, "
        "lighting, rendering, colors, painting, blurry, sketchy, messy, "
        "dirty lines, grayscale, halftone, textures, 3d, photorealistic, "
        "watercolor, oil painting, "
    ),
    
    "flat_color": (
        "western style, realistic lighting, complex shading, gradients, "
        "soft shading, detailed rendering, intricate textures, "
        "ambient occlusion, subsurface scattering, photorealistic, 3d render, "
        "oil painting, impressionism, blurry, hdr, "
    ),
    
    "final_render": (
        "score_4, score_3, score_2, score_1, score_0, text, watermark, "
        "ugly, worst quality, low quality, normal quality, bad anatomy, "
        "bad hands, missing fingers, extra fingers, extra limbs, "
        "fused fingers, deformed hands, malformed limbs, blurry, grainy, "
        "noisy, pixelated, low resolution, signature, artist name, "
        "western comic, American comic, realistic, photorealistic, "
    ),
}

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
        # 获取当前步骤的专属负面词
        step_negative = _STEP_NEGATIVES.get(step, "")
        
        # 获取通用的负面词
        base_negative = persona_negative or _DEFAULT_NEGATIVE
        
        # 合并两者
        final_negative = f"{step_negative}, {base_negative}" if step_negative else base_negative

        if refine:
            positive = await self._refine_with_ollama(step, positive)

        return positive, final_negative

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
            print(f"[prompts] Ollama refinement failed for step '{step}': {exc}")
            return prompt


# Module-level singleton
prompt_enhancer = PromptEnhancer()
