# engine.py
import random
import torch
from PIL import Image
from diffusers import StableDiffusionControlNetPipeline, ControlNetModel
from .config import Config


class AIEngine:
    """AI 绘画生成引擎（单例）。

    使用 StableDiffusionControlNetPipeline，针对 16 GB 显存启用
    ``enable_model_cpu_offload()`` 以节省显存占用。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._pipeline: StableDiffusionControlNetPipeline = self._load_pipeline()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _load_pipeline(self) -> StableDiffusionControlNetPipeline:
        """加载 ControlNet + Stable Diffusion 管线。"""
        controlnet = ControlNetModel.from_pretrained(
            Config.CONTROLNET_MODEL_ID,
            torch_dtype=torch.float16,
        )
        pipeline = StableDiffusionControlNetPipeline.from_pretrained(
            Config.SD_MODEL_ID,
            controlnet=controlnet,
            torch_dtype=torch.float16,
            safety_checker=None,
        )
        # 针对 16 GB 显存：模型各子组件按需移入显存，不再常驻
        pipeline.enable_model_cpu_offload()
        return pipeline

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def generate_single(self, prompt: str, step_name: str = "") -> tuple[Image.Image, int]:
        """供定时任务调用的单张图片生成接口。

        当没有上一步骤图作为 ControlNet 条件时，使用纯白占位图作为
        condition image（ControlNet 权重置为 0），退化为普通 txt2img。

        Args:
            prompt:    正向提示词。
            step_name: 步骤名称（仅用于日志）。

        Returns:
            (image, seed) 元组。
        """
        seed = random.randint(0, 2**32 - 1)
        generator = torch.manual_seed(seed)

        # 纯白占位图作为 "无条件" 的 ControlNet 输入
        blank_control = Image.new("RGB", (Config.IMAGE_WIDTH, Config.IMAGE_HEIGHT), color=(255, 255, 255))

        result = self._pipeline(
            prompt=prompt,
            image=blank_control,
            controlnet_conditioning_scale=0.0,   # 关闭 ControlNet 影响
            num_inference_steps=30,
            generator=generator,
        )
        return result.images[0], seed

    def generate(
        self,
        step_config: dict,
        prev_image: Image.Image | None = None,
    ) -> tuple[Image.Image, int]:
        """交互式生成接口，供逐步绘制流程调用。

        Args:
            step_config: 包含 ``prompt`` 和可选
                ``controlnet_conditioning_scale`` 的字典。
            prev_image:  上一步骤的输出图片，作为 ControlNet 条件输入。
                         若为 None 则使用纯白占位图。

        Returns:
            (image, seed) 元组。
        """
        seed = random.randint(0, 2**32 - 1)
        generator = torch.manual_seed(seed)

        prompt = step_config.get("prompt", "")
        conditioning_scale = step_config.get("controlnet_conditioning_scale", 1.0)

        if prev_image is None:
            control_image = Image.new("RGB", (Config.IMAGE_WIDTH, Config.IMAGE_HEIGHT), color=(255, 255, 255))
            conditioning_scale = 0.0
        else:
            control_image = prev_image.convert("RGB").resize((Config.IMAGE_WIDTH, Config.IMAGE_HEIGHT))

        result = self._pipeline(
            prompt=prompt,
            image=control_image,
            controlnet_conditioning_scale=float(conditioning_scale),
            num_inference_steps=30,
            generator=generator,
        )
        return result.images[0], seed


# 模块级单例，供其他模块直接导入使用
engine = AIEngine()
