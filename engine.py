# engine.py
import os
import time
import random
import torch
from pathlib import Path
from PIL import Image

# ---------------------------------------------------------------------------
# 网络配置：优先使用镜像站，降低国内用户连接失败率
# ---------------------------------------------------------------------------
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
print(f"Using HF Endpoint: {os.environ['HF_ENDPOINT']}")

from diffusers import StableDiffusionControlNetPipeline, ControlNetModel
from .config import Config

# ---------------------------------------------------------------------------
# 下载重试配置
# ---------------------------------------------------------------------------
# 依次尝试的 HF 端点列表；每个端点最多重试 _RETRIES_PER_ENDPOINT 次。
_HF_ENDPOINTS = [
    "https://hf-mirror.com",
    "https://huggingface.co",
]
_RETRIES_PER_ENDPOINT = 3
_RETRY_BASE_DELAY = 5  # 秒，实际等待时间 = base * attempt


def _load_with_retry(loader_fn, description: str = ""):
    """在多个 HF 端点上带退避重试地执行 loader_fn。

    Args:
        loader_fn:   无参可调用对象，执行实际的 from_pretrained 调用。
        description: 用于日志的描述字符串。

    Returns:
        loader_fn 的返回值。

    Raises:
        RuntimeError: 所有端点全部重试失败后抛出，附带操作指引。
    """
    last_exc: Exception | None = None
    attempt = 0
    for endpoint in _HF_ENDPOINTS:
        os.environ["HF_ENDPOINT"] = endpoint
        for retry in range(_RETRIES_PER_ENDPOINT):
            attempt += 1
            print(
                f"[{description}] 第 {attempt} 次尝试"
                f"（端点: {endpoint}，本端点第 {retry + 1}/{_RETRIES_PER_ENDPOINT} 次）"
            )
            try:
                result = loader_fn()
                print(f"[{description}] 下载成功（端点: {endpoint}）")
                return result
            except Exception as exc:
                last_exc = exc
                print(f"[{description}] 失败: {exc}")
                if retry < _RETRIES_PER_ENDPOINT - 1:
                    wait = _RETRY_BASE_DELAY * (2 ** retry)
                    print(f"  → {wait} 秒后重试…")
                    time.sleep(wait)
    raise RuntimeError(
        f"[{description}] 所有端点（{_HF_ENDPOINTS}）均下载失败。\n"
        f"最后错误: {last_exc}\n\n"
        "请参阅 README 中的【手动下载模型】章节，通过其他途径下载后配置本地路径。"
    ) from last_exc


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

    @staticmethod
    def _resolve_source(local_cfg: str, remote_id: str, label: str) -> tuple[str, bool]:
        """返回 (source, is_local)。

        若 local_cfg 已配置且对应路径存在则视为本地模型；否则使用远端 ID。
        """
        if local_cfg:
            p = Path(local_cfg)
            if p.exists():
                print(f"[{label}] 使用本地路径: {p.resolve()}")
                return str(p), True
            else:
                print(
                    f"[{label}] 警告: 配置了本地路径 '{local_cfg}' 但目录不存在，"
                    "将回退到网络下载。"
                )
        print(f"[{label}] 将从网络下载: {remote_id}")
        return remote_id, False

    def _load_pipeline(self) -> StableDiffusionControlNetPipeline:
        """加载 ControlNet + Stable Diffusion 管线。

        加载顺序：
        1. 若 ``Config.LOCAL_CONTROLNET_PATH`` / ``Config.LOCAL_MODEL_PATH``
           已配置且目录存在，直接从本地磁盘加载，完全不需要网络。
        2. 否则通过网络下载，自动在多个 HF 端点间重试。
        """
        cn_source, cn_local = self._resolve_source(
            Config.LOCAL_CONTROLNET_PATH, Config.CONTROLNET_MODEL_ID, "ControlNet"
        )
        sd_source, sd_local = self._resolve_source(
            Config.LOCAL_MODEL_PATH, Config.SD_MODEL_ID, "SD"
        )

        def _load_controlnet():
            return ControlNetModel.from_pretrained(
                cn_source,
                torch_dtype=torch.float16,
                local_files_only=cn_local,
            )

        if cn_local:
            controlnet = _load_controlnet()
        else:
            controlnet = _load_with_retry(_load_controlnet, "ControlNet")

        def _load_sd():
            return StableDiffusionControlNetPipeline.from_pretrained(
                sd_source,
                controlnet=controlnet,
                torch_dtype=torch.float16,
                safety_checker=None,
                local_files_only=sd_local,
            )

        if sd_local:
            pipeline = _load_sd()
        else:
            pipeline = _load_with_retry(_load_sd, "SD")

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
