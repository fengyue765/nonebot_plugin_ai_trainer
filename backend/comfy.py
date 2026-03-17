"""ComfyUI API client.

Handles image uploading, workflow queuing, and result retrieval via
the ComfyUI WebSocket + HTTP API.
"""

import json
import uuid
import asyncio
import aiohttp
from pathlib import Path
from typing import Optional

from ..config import Config

# Directory where workflow JSON files are stored
_WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"


async def _load_workflow(name: str) -> dict:
    """Load a workflow JSON file from the workflows directory."""
    path = _WORKFLOW_DIR / name
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, path.read_text, "utf-8")
    return json.loads(data)


class ComfyClient:
    """Async client for the ComfyUI API."""

    def __init__(self, base_url: str = Config.COMFY_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.http_url = f"http://{self.base_url}"
        self.ws_url = f"ws://{self.base_url}/ws"
        self.client_id = str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def upload_image(self, image_bytes: bytes, filename: str = "input.png") -> str:
        """Upload an image to ComfyUI and return the server-side filename."""
        form = aiohttp.FormData()
        form.add_field(
            "image",
            image_bytes,
            filename=filename,
            content_type="image/png",
        )
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.http_url}/upload/image", data=form
                ) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    return result["name"]
        except Exception as exc:
            raise RuntimeError(f"ComfyUI upload_image failed: {exc}") from exc

    async def queue_prompt(self, workflow: dict) -> str:
        """Submit a workflow to the ComfyUI prompt queue.

        Returns the prompt_id assigned by the server.
        """
        payload = {"prompt": workflow, "client_id": self.client_id}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.http_url}/prompt", json=payload
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
                    return data["prompt_id"]
        except Exception as exc:
            raise RuntimeError(f"ComfyUI queue_prompt failed: {exc}") from exc

    async def wait_for_result(self, prompt_id: str, timeout: float = 120.0) -> list[bytes]:
        """Wait on the WebSocket until the prompt finishes, then fetch output images.

        Args:
            prompt_id: The prompt ID returned by :meth:`queue_prompt`.
            timeout:   Maximum seconds to wait.

        Returns:
            List of raw PNG bytes for each output image.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(
                    f"{self.ws_url}?clientId={self.client_id}"
                ) as ws:
                    async with asyncio.timeout(timeout):
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if (
                                    data.get("type") == "executing"
                                    and data.get("data", {}).get("node") is None
                                    and data.get("data", {}).get("prompt_id") == prompt_id
                                ):
                                    break
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                raise RuntimeError("WebSocket closed unexpectedly")
        except TimeoutError as exc:
            raise RuntimeError(
                f"ComfyUI timed out waiting for prompt {prompt_id}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"ComfyUI WebSocket error: {exc}") from exc

        return await self._fetch_images(prompt_id)

    async def _fetch_images(self, prompt_id: str) -> list[bytes]:
        """Retrieve output images for a completed prompt via HTTP."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.http_url}/history/{prompt_id}"
                ) as resp:
                    resp.raise_for_status()
                    history = await resp.json()

                output_images: list[bytes] = []
                prompt_data = history.get(prompt_id, {})
                for node_output in prompt_data.get("outputs", {}).values():
                    for img_info in node_output.get("images", []):
                        params = {
                            "filename": img_info["filename"],
                            "subfolder": img_info.get("subfolder", ""),
                            "type": img_info.get("type", "output"),
                        }
                        async with session.get(
                            f"{self.http_url}/view", params=params
                        ) as img_resp:
                            img_resp.raise_for_status()
                            output_images.append(await img_resp.read())

                return output_images
        except Exception as exc:
            raise RuntimeError(f"ComfyUI _fetch_images failed: {exc}") from exc

    # ------------------------------------------------------------------
    # High-level workflow methods
    # ------------------------------------------------------------------

    async def step1_sketch(
        self,
        positive_prompt: str,
        negative_prompt: str = "",
    ) -> bytes:
        """Run the Txt2Img workflow to generate an initial sketch.

        Args:
            positive_prompt: Positive prompt text.
            negative_prompt: Negative prompt text.

        Returns:
            Raw PNG bytes of the generated image.
        """
        workflow = await _load_workflow("workflow_step1.json")

        # Inject prompts into the workflow nodes
        for node in workflow.values():
            if node.get("class_type") == "CLIPTextEncode":
                meta = node.get("_meta", {})
                if meta.get("title") == "positive":
                    node["inputs"]["text"] = positive_prompt
                elif meta.get("title") == "negative":
                    node["inputs"]["text"] = negative_prompt

        prompt_id = await self.queue_prompt(workflow)
        images = await self.wait_for_result(prompt_id)
        if not images:
            raise RuntimeError("step1_sketch returned no images")
        return images[0]

    async def stepx_img2img(
        self,
        input_image_bytes: bytes,
        positive_prompt: str,
        negative_prompt: str = "",
        denoising_strength: float = 0.75,
    ) -> bytes:
        """Run the Img2Img + Canny ControlNet workflow.

        Args:
            input_image_bytes:  PNG bytes of the previous step's output.
            positive_prompt:    Positive prompt text.
            negative_prompt:    Negative prompt text.
            denoising_strength: How much to deviate from the input image.

        Returns:
            Raw PNG bytes of the generated image.
        """
        workflow = await _load_workflow("workflow_img2img.json")

        # Upload the source image and wire it into the workflow
        server_filename = await self.upload_image(input_image_bytes, "img2img_input.png")

        for node in workflow.values():
            if node.get("class_type") == "LoadImage":
                node["inputs"]["image"] = server_filename
            elif node.get("class_type") == "KSampler":
                node["inputs"]["denoise"] = denoising_strength
            elif node.get("class_type") == "CLIPTextEncode":
                meta = node.get("_meta", {})
                if meta.get("title") == "positive":
                    node["inputs"]["text"] = positive_prompt
                elif meta.get("title") == "negative":
                    node["inputs"]["text"] = negative_prompt

        prompt_id = await self.queue_prompt(workflow)
        images = await self.wait_for_result(prompt_id)
        if not images:
            raise RuntimeError("stepx_img2img returned no images")
        return images[0]

    async def get_image_tags(self, image_bytes: bytes) -> str:
        """Run the WD14 Tagger workflow to extract tags from an image.

        Args:
            image_bytes: PNG bytes of the image to tag.

        Returns:
            Comma-separated tag string produced by the tagger.
        """
        workflow = await _load_workflow("workflow_tagger.json")

        server_filename = await self.upload_image(image_bytes, "tagger_input.png")

        for node in workflow.values():
            if node.get("class_type") == "LoadImage":
                node["inputs"]["image"] = server_filename

        prompt_id = await self.queue_prompt(workflow)

        # The tagger stores its output in history rather than image files
        try:
            async with aiohttp.ClientSession() as session:
                # Wait for completion
                async with session.ws_connect(
                    f"{self.ws_url}?clientId={self.client_id}"
                ) as ws:
                    async with asyncio.timeout(60.0):
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                if (
                                    data.get("type") == "executing"
                                    and data.get("data", {}).get("node") is None
                                    and data.get("data", {}).get("prompt_id") == prompt_id
                                ):
                                    break

                async with session.get(
                    f"{self.http_url}/history/{prompt_id}"
                ) as resp:
                    resp.raise_for_status()
                    history = await resp.json()

                prompt_data = history.get(prompt_id, {})
                for node_output in prompt_data.get("outputs", {}).values():
                    tags = node_output.get("tags")
                    if tags:
                        return tags if isinstance(tags, str) else ", ".join(tags)

                return ""
        except Exception as exc:
            raise RuntimeError(f"get_image_tags failed: {exc}") from exc
