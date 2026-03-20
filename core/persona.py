"""Persona manager.

Manages artist style "personas". Each persona has:
- positive_prompt: core positive tags that define the style
- negative_prompt: core negative tags to avoid
- description:     human-readable description of the style

Personas are persisted as JSON and the active persona is tracked.
Ollama (dolphin-llama3) is used to analyse image tags and generate
new personas automatically.
"""

import json
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional

from ..config import Config
from ..backend.comfy import comfy_client


class PersonaManager:
    """Manages artist style personas, backed by a JSON file."""

    def __init__(
        self,
        persona_file: str = Config.PERSONA_FILE,
        ollama_url: str = Config.OLLAMA_URL,
        ollama_model: str = Config.OLLAMA_MODEL,
    ) -> None:
        self._path = Path(persona_file)
        self._ollama_url = ollama_url.rstrip("/")
        self._ollama_model = ollama_model
        self._data: dict = self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {"active": None, "personas": {}}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def active_name(self) -> Optional[str]:
        return self._data.get("active")

    @property
    def active_persona(self) -> Optional[dict]:
        name = self.active_name
        if name:
            return self._data["personas"].get(name)
        return None

    def list_personas(self) -> list[str]:
        return list(self._data["personas"].keys())

    def get_persona(self, name: str) -> Optional[dict]:
        return self._data["personas"].get(name)

    # 在 list_personas 方法之后添加
    def get_persona_name(self, persona: dict) -> Optional[str]:
        """根据 persona 对象获取名称"""
        for name, p in self._data["personas"].items():
            if p == persona:
                return name
        return None

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def switch_persona(self, name: str) -> bool:
        """Set the active persona. Returns False if the name does not exist."""
        if name not in self._data["personas"]:
            return False
        self._data["active"] = name
        self._save()
        return True

    def delete_persona(self, name: str) -> bool:
        """Delete a persona by name. Returns False if it does not exist."""
        if name not in self._data["personas"]:
            return False
        del self._data["personas"][name]
        if self._data["active"] == name:
            self._data["active"] = None
        self._save()
        return True

    def add_persona(
        self,
        name: str,
        positive_prompt: str,
        negative_prompt: str,
        description: str,
    ) -> None:
        """Manually add or overwrite a persona."""
        self._data["personas"][name] = {
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "description": description,
        }
        self._save()

    # ------------------------------------------------------------------
    # Ollama-assisted persona creation
    # ------------------------------------------------------------------

    async def create_persona_from_tags(
        self, name: str, tags: str
    ) -> dict:
        """Analyse image tags with Ollama and create a new persona.

        Args:
            name: Name to give the new persona.
            tags: Comma-separated tag string from the WD14 tagger.

        Returns:
            The newly created persona dict.
        """
        positive, negative, description = await self._analyze_tags_with_ollama(tags)
        self.add_persona(name, positive, negative, description)
        return self._data["personas"][name]

    async def _analyze_tags_with_ollama(
        self, tags: str
    ) -> tuple[str, str, str]:
        """Send tags to Ollama and parse out positive/negative prompts and a description.

        Returns a (positive_prompt, negative_prompt, description) tuple.
        Falls back to a basic extraction if the API call fails.
        """
        system_prompt = (
            "You are an expert in anime character design and character sheet analysis.\n"
            "Your task is to extract ONLY the character's FIXED FEATURES from the given tags.\n\n"
            "FIXED FEATURES include:\n"
            "- Physical appearance: hair color (blonde, black, white, etc.), hair style (long hair, ponytail, twin tails, etc.)\n"
            "- Eye color and shape: blue eyes, red eyes, closed eyes, etc.\n"
            "- Body features: large breasts, petite, tall, etc.\n"
            "- Clothing style: school uniform, maid outfit, kimono, casual wear, etc. (general style, not specific poses)\n"
            "- Accessories: hair ribbon, earrings, glasses, gloves, hat, necklace, etc.\n"
            "- Skin features: blush, freckles, beauty mark, etc.\n\n"
            "DO NOT include:\n"
            "- Actions/poses: sitting, standing, running, spread legs, etc.\n"
            "- Scenes/backgrounds: outdoors, indoors, forest, classroom, etc.\n"
            "- Emotions/expressions: smiling, angry, crying, etc.\n"
            "- Lighting/effects: backlighting, sparkles, etc.\n"
            "- Camera angles: from above, close-up, etc.\n\n"
            "Reply with exactly three lines:\n"
            "POSITIVE: <comma-separated fixed feature tags ONLY>\n"
            "NEGATIVE: <comma-separated tags to avoid (optional)>\n"
            "DESCRIPTION: <one-sentence description of the character design, as short as possible>"
        )
        user_prompt = f"Extract fixed character features from these tags: {tags}"

        try:
            # Free ComfyUI VRAM so Ollama can load its model
            await comfy_client.unload_models()

            payload = {
                "model": self._ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "keep_alive": 0,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self._ollama_url}/api/chat", json=payload, timeout=aiohttp.ClientTimeout(total=Config.OLLAMA_TIMEOUT)
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    content: str = data["message"]["content"]

            return self._parse_ollama_response(content)

        except Exception as exc:
            print(f"[persona] Ollama call failed, using fallback: {exc}")
            return self._fallback_extraction(tags)

    @staticmethod
    def _parse_ollama_response(content: str) -> tuple[str, str, str]:
        positive = ""
        negative = ""
        description = ""
        for line in content.splitlines():
            if line.upper().startswith("POSITIVE:"):
                positive = line.split(":", 1)[1].strip()
            elif line.upper().startswith("NEGATIVE:"):
                negative = line.split(":", 1)[1].strip()
            elif line.upper().startswith("DESCRIPTION:"):
                description = line.split(":", 1)[1].strip()
        return positive, negative, description

    @staticmethod
    def _fallback_extraction(tags: str) -> tuple[str, str, str]:
        """Basic tag splitting when Ollama is unavailable."""
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        positive = ", ".join(tag_list[:20])
        negative = "lowres, blurry, bad anatomy"
        description = f"Auto-extracted style from {len(tag_list)} tags"
        return positive, negative, description


# Module-level singleton
persona_manager = PersonaManager()
