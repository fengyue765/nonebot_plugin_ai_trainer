"""ComfyUI API client with enhanced timeout handling."""

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
        # 增加重试次数和超时时间
        self.max_retries = 3
        self.default_timeout = 180.0  # 增加到180秒

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
        
        for attempt in range(self.max_retries):
            try:
                print(f"[DEBUG ComfyUI] 上传图片尝试 {attempt + 1}/{self.max_retries}")
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.http_url}/upload/image", data=form, timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        resp.raise_for_status()
                        result = await resp.json()
                        print(f"[DEBUG ComfyUI] 图片上传成功: {result['name']}")
                        return result["name"]
            except Exception as exc:
                print(f"[DEBUG ComfyUI] 上传图片失败 (尝试 {attempt + 1}): {exc}")
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"ComfyUI upload_image failed after {self.max_retries} attempts: {exc}") from exc
                await asyncio.sleep(2)  # 等待2秒后重试

    async def queue_prompt(self, workflow: dict) -> str:
        """Submit a workflow to the ComfyUI prompt queue.
        
        Returns the prompt_id assigned by the server.
        """
        payload = {"prompt": workflow, "client_id": self.client_id}
        
        for attempt in range(self.max_retries):
            try:
                print(f"[DEBUG ComfyUI] 提交工作流尝试 {attempt + 1}/{self.max_retries}")
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        f"{self.http_url}/prompt", json=payload, timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        resp.raise_for_status()
                        data = await resp.json()
                        prompt_id = data["prompt_id"]
                        print(f"[DEBUG ComfyUI] 工作流提交成功, prompt_id: {prompt_id}")
                        return prompt_id
            except Exception as exc:
                print(f"[DEBUG ComfyUI] 提交工作流失败 (尝试 {attempt + 1}): {exc}")
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"ComfyUI queue_prompt failed after {self.max_retries} attempts: {exc}") from exc
                await asyncio.sleep(2)

    async def wait_for_result(self, prompt_id: str, timeout: Optional[float] = None) -> list[bytes]:
        """Wait on the WebSocket until the prompt finishes, then fetch output images.

        Args:
            prompt_id: The prompt ID returned by :meth:`queue_prompt`.
            timeout:   Maximum seconds to wait. If None, uses self.default_timeout.

        Returns:
            List of raw PNG bytes for each output image.
        """
        if timeout is None:
            timeout = self.default_timeout
            
        # print(f"[DEBUG ComfyUI] ===== 开始等待 prompt {prompt_id} =====")
        # print(f"[DEBUG ComfyUI] 超时设置: {timeout}秒")
        print(f"[DEBUG ComfyUI] WebSocket URL: {self.ws_url}?clientId={self.client_id}")
        
        # 先检查 ComfyUI 是否在线
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.http_url}/system_stats", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        stats = await resp.json()
                        # print(f"[DEBUG ComfyUI] 系统状态: {stats}")
                    else:
                        print(f"[DEBUG ComfyUI] 系统状态检查失败: {resp.status}")
        except Exception as e:
            print(f"[DEBUG ComfyUI] 无法连接到 ComfyUI: {e}")
        
        try:
            async with aiohttp.ClientSession() as session:
                # print(f"[DEBUG ComfyUI] 正在连接 WebSocket...")
                async with session.ws_connect(
                    f"{self.ws_url}?clientId={self.client_id}",
                    timeout=30.0
                ) as ws:
                    print(f"[DEBUG ComfyUI] WebSocket 连接成功")
                    start_time = asyncio.get_event_loop().time()
                    
                    async with asyncio.timeout(timeout):
                        msg_count = 0
                        async for msg in ws:
                            msg_count += 1
                            elapsed = asyncio.get_event_loop().time() - start_time
                            
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                msg_type = data.get("type")
                                
                                # 打印所有消息类型（调试用）
                                # if msg_type in ["executing", "progress", "execution_start", "execution_cached"]:
                                    # print(f"[DEBUG ComfyUI] 消息 #{msg_count} (已耗时 {elapsed:.1f}秒): {msg_type}")
                                
                                if msg_type == "executing":
                                    node = data.get("data", {}).get("node")
                                    prompt = data.get("data", {}).get("prompt_id")
                                    
                                    # if node is not None:
                                        # print(f"[DEBUG ComfyUI] 正在执行节点: {node}")
                                    
                                    if node is None and prompt == prompt_id:
                                        print(f"[DEBUG ComfyUI] prompt {prompt_id} 执行完成，总耗时: {elapsed:.1f}秒")
                                        break
                                
                                elif msg_type == "progress":
                                    # 打印进度信息
                                    progress_data = data.get("data", {})
                                    current = progress_data.get("value", 0)
                                    max_val = progress_data.get("max", 100)
                                    # print(f"[DEBUG ComfyUI] 进度: {current}/{max_val} ({current/max_val*100:.1f}%)")
                            
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                print(f"[DEBUG ComfyUI] WebSocket 意外关闭: {msg.type}")
                                raise RuntimeError(f"WebSocket closed unexpectedly: {msg.type}")
                    
                    print(f"[DEBUG ComfyUI] WebSocket 监听结束，开始获取图片")
                    
        except asyncio.TimeoutError:
            print(f"[DEBUG ComfyUI] 超时错误: 等待 prompt {prompt_id} 超过 {timeout}秒")
            # 尝试获取队列状态
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.http_url}/queue", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            queue_info = await resp.json()
                            print(f"[DEBUG ComfyUI] 当前队列状态: {queue_info}")
            except:
                pass
            raise RuntimeError(f"ComfyUI timed out waiting for prompt {prompt_id}")
            
        except Exception as exc:
            print(f"[DEBUG ComfyUI] WebSocket 错误: {exc}")
            raise RuntimeError(f"ComfyUI WebSocket error: {exc}") from exc

        return await self._fetch_images(prompt_id)

    async def _fetch_images(self, prompt_id: str) -> list[bytes]:
        """Retrieve output images for a completed prompt via HTTP."""
        # print(f"[DEBUG ComfyUI] ===== 获取 prompt {prompt_id} 的输出图片 =====")
        
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession() as session:
                    # 先获取历史记录
                    history_url = f"{self.http_url}/history/{prompt_id}"
                    print(f"[DEBUG ComfyUI] 请求历史记录 (尝试 {attempt + 1}): {history_url}")
                    
                    async with session.get(history_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        resp.raise_for_status()
                        history = await resp.json()
                        print(f"[DEBUG ComfyUI] 历史记录响应成功")

                    output_images: list[bytes] = []
                    prompt_data = history.get(prompt_id, {})
                    outputs = prompt_data.get("outputs", {})
                    
                    if not outputs:
                        print(f"[DEBUG ComfyUI] 警告: 没有找到输出节点")
                        # 尝试获取完整的history
                        async with session.get(f"{self.http_url}/history", timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            all_history = await resp.json()
                            print(f"[DEBUG ComfyUI] 所有历史记录 keys: {list(all_history.keys())}")
                    
                    for node_id, node_output in outputs.items():
                        images = node_output.get("images", [])
                        # print(f"[DEBUG ComfyUI] 节点 {node_id} 输出图片数: {len(images)}")
                        
                        for img_info in images:
                            # print(f"[DEBUG ComfyUI] 图片信息: {img_info}")
                            params = {
                                "filename": img_info["filename"],
                                "subfolder": img_info.get("subfolder", ""),
                                "type": img_info.get("type", "output"),
                            }
                            
                            view_url = f"{self.http_url}/view"
                            async with session.get(view_url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as img_resp:
                                img_resp.raise_for_status()
                                img_data = await img_resp.read()
                                # print(f"[DEBUG ComfyUI] 图片下载成功，大小: {len(img_data)} 字节")
                                output_images.append(img_data)

                    print(f"[DEBUG ComfyUI] 总共获取到 {len(output_images)} 张图片")
                    
                    if not output_images:
                        print(f"[DEBUG ComfyUI] 警告: 没有获取到任何图片")
                        if attempt < self.max_retries - 1:
                            print(f"[DEBUG ComfyUI] 等待后重试...")
                            await asyncio.sleep(3)
                            continue
                    
                    return output_images
                    
            except Exception as exc:
                print(f"[DEBUG ComfyUI] _fetch_images 尝试 {attempt + 1} 失败: {exc}")
                if attempt == self.max_retries - 1:
                    raise RuntimeError(f"ComfyUI _fetch_images failed after {self.max_retries} attempts: {exc}") from exc
                await asyncio.sleep(3)

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
        # print(f"[DEBUG ComfyUI] ===== step1_sketch 开始 =====")
        # print(f"[DEBUG ComfyUI] 正面词: {positive_prompt[:100]}...")
        
        workflow = await _load_workflow("workflow_step1.json")
        print(f"[DEBUG ComfyUI] 工作流加载成功")

        # Inject prompts into the workflow nodes
        for node_id, node in workflow.items():
            if node.get("class_type") == "CLIPTextEncode":
                meta = node.get("_meta", {})
                if meta.get("title") == "positive":
                    print(f"[DEBUG ComfyUI] 注入正面词到节点 {node_id}")
                    node["inputs"]["text"] = positive_prompt
                elif meta.get("title") == "negative":
                    print(f"[DEBUG ComfyUI] 注入负面词到节点 {node_id}")
                    node["inputs"]["text"] = negative_prompt

        prompt_id = await self.queue_prompt(workflow)
        images = await self.wait_for_result(prompt_id)
        
        if not images:
            raise RuntimeError("step1_sketch returned no images")
        
        print(f"[DEBUG ComfyUI] step1_sketch 成功，返回图片大小: {len(images[0])} 字节")
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

    async def unload_models(self) -> None:
        """Ask ComfyUI to release VRAM so that Ollama can load its models.

        Attempts to call the ``/free`` endpoint provided by ComfyUI-Manager and
        the built-in ``/interrupt`` endpoint.  Both calls are fire-and-forget:
        failures are silently swallowed because VRAM management is best-effort
        and should never block the main pipeline.
        """
        try:
            async with aiohttp.ClientSession() as session:
                for path in ("/free", "/interrupt"):
                    try:
                        async with session.post(f"{self.http_url}{path}") as resp:
                            # Consume the response body to avoid connection leaks
                            await resp.read()
                    except Exception:
                        pass
        except Exception:
            pass

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


# Module-level singleton
comfy_client = ComfyClient()