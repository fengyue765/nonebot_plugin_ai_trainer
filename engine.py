# engine.py
"""AI 绘画引擎模块。

重要：os.environ["HF_ENDPOINT"] 必须在所有 HuggingFace 相关导入之前设置，
否则镜像加速不会生效。因此本模块开头先设置环境变量，再进行其他导入。
"""

import os
import time
import random
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# !! CRITICAL !! 必须在所有 HuggingFace 库导入之前设置，才能让镜像加速生效
# ---------------------------------------------------------------------------
from .config import Config as _Cfg  # noqa: E402  (intentional early import)

if _Cfg.HF_MIRROR:
    os.environ["HF_ENDPOINT"] = _Cfg.HF_ENDPOINT_MIRROR
    print(f"[ai_trainer] HF Mirror 已启用: {_Cfg.HF_ENDPOINT_MIRROR}")
else:
    os.environ.setdefault("HF_ENDPOINT", _Cfg.HF_ENDPOINT_OFFICIAL)
    print(f"[ai_trainer] 使用官方 HF Endpoint: {_Cfg.HF_ENDPOINT_OFFICIAL}")

# ---------------------------------------------------------------------------
# 现在才导入 HuggingFace 相关库
# ---------------------------------------------------------------------------
import torch
from PIL import Image
from diffusers import (
    ControlNetModel,
    MultiControlNetModel,
    StableDiffusionControlNetPipeline,
)

# ---------------------------------------------------------------------------
# 下载重试配置
# ---------------------------------------------------------------------------
_RETRY_ENDPOINTS = [_Cfg.HF_ENDPOINT_MIRROR, _Cfg.HF_ENDPOINT_OFFICIAL]
_RETRIES_PER_ENDPOINT = 3
_RETRY_BASE_DELAY = 5  # 秒，实际等待 = base * 2^retry（指数退避）


def _load_with_retry(loader_fn, description: str = ""):
    """对 loader_fn 按端点列表带退避重试执行。

    Args:
        loader_fn:   无参可调用对象，内部执行 from_pretrained 等下载操作。
        description: 用于日志的描述字符串。

    Returns:
        loader_fn 的返回值。

    Raises:
        RuntimeError: 所有端点全部重试失败后抛出。
    """
    last_exc: Optional[Exception] = None
    attempt = 0
    for endpoint in _RETRY_ENDPOINTS:
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
        f"[{description}] 所有端点均下载失败。\n"
        f"最后错误: {last_exc}\n\n"
        "请参阅 README 中的【手动下载模型】章节，通过其他途径下载后配置本地路径。"
    ) from last_exc


def _resolve_source(local_cfg: str, remote_id: str, label: str) -> tuple[str, bool]:
    """返回 (source, is_local)。

    若 local_cfg 已配置且对应路径存在，则使用本地路径；否则使用远端 ID。
    """
    if local_cfg:
        p = Path(local_cfg)
        if p.exists():
            print(f"[{label}] 使用本地路径: {p.resolve()}")
            return str(p), True
        print(
            f"[{label}] 警告: 本地路径 '{local_cfg}' 不存在，将回退到网络下载。"
        )
    print(f"[{label}] 将从网络下载: {remote_id}")
    return remote_id, False


class ArtEngine:
    """AI 绘画生成引擎（单例）。

    内部使用 ``StableDiffusionControlNetPipeline`` + ``MultiControlNetModel``
    （OpenPose 用于阶段 1 构图，Canny 用于阶段 2-4 精修），并默认开启
    ``enable_model_cpu_offload()`` 以适应 16 GB 以内的显存环境。

    Usage::

        engine = ArtEngine()
        image, seed = engine.generate(stage_config, prev_image=None)
    """

    _instance: Optional["ArtEngine"] = None

    def __new__(cls) -> "ArtEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[attr-defined]
            return
        self._initialized = True
        self._pipeline: StableDiffusionControlNetPipeline = self._build_pipeline()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _build_pipeline(self) -> StableDiffusionControlNetPipeline:
        """构建 MultiControlNet + Stable Diffusion 管线。

        加载策略（优先级从高到低）：
        1. 若 Config 中配置了本地路径且目录存在 → 从磁盘加载，完全离线。
        2. 否则通过网络下载，自动在多个 HF 端点间重试（先镜像站，再官方源）。
        """
        openpose_src, openpose_local = _resolve_source(
            _Cfg.LOCAL_OPENPOSE_PATH, _Cfg.OPENPOSE_CONTROLNET_ID, "ControlNet-OpenPose"
        )
        canny_src, canny_local = _resolve_source(
            _Cfg.LOCAL_CANNY_PATH, _Cfg.CANNY_CONTROLNET_ID, "ControlNet-Canny"
        )
        sd_src, sd_local = _resolve_source(
            _Cfg.LOCAL_SD_PATH, _Cfg.SD_MODEL_ID, "SD-1.5"
        )

        # 加载 ControlNet-OpenPose
        def _load_openpose():
            return ControlNetModel.from_pretrained(
                openpose_src,
                torch_dtype=torch.float16,
                local_files_only=openpose_local,
            )

        controlnet_openpose: ControlNetModel = (
            _load_openpose() if openpose_local
            else _load_with_retry(_load_openpose, "ControlNet-OpenPose")
        )

        # 加载 ControlNet-Canny
        def _load_canny():
            return ControlNetModel.from_pretrained(
                canny_src,
                torch_dtype=torch.float16,
                local_files_only=canny_local,
            )

        controlnet_canny: ControlNetModel = (
            _load_canny() if canny_local
            else _load_with_retry(_load_canny, "ControlNet-Canny")
        )

        # 组合为 MultiControlNetModel（索引 0=OpenPose，索引 1=Canny）
        multi_controlnet = MultiControlNetModel([controlnet_openpose, controlnet_canny])

        # 加载 Stable Diffusion 1.5
        def _load_sd():
            return StableDiffusionControlNetPipeline.from_pretrained(
                sd_src,
                controlnet=multi_controlnet,
                torch_dtype=torch.float16,
                safety_checker=None,
                local_files_only=sd_local,
            )

        pipeline: StableDiffusionControlNetPipeline = (
            _load_sd() if sd_local
            else _load_with_retry(_load_sd, "SD-1.5")
        )

        # 按需在 CPU↔GPU 之间调度子组件，降低峰值显存占用
        pipeline.enable_model_cpu_offload()
        return pipeline

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------

    def generate(
        self,
        stage_config: dict,
        prev_image: Optional[Image.Image] = None,
    ) -> tuple[Image.Image, int]:
        """生成单张图片。

        Args:
            stage_config: 包含以下键的字典：

                - ``prompt``      (str):   正向提示词。
                - ``controlnet``  (str):   使用哪个 ControlNet，
                  可选值 ``"openpose"`` / ``"canny"`` / ``"none"``。
                - ``scale``       (float): ControlNet 权重，0.0 表示完全禁用。

            prev_image: 上一阶段的输出图片，作为 ControlNet 的条件输入。
                        若为 None，则使用纯白占位图（等效于 txt2img）。

        Returns:
            ``(image, seed)`` 元组。
        """
        seed = random.randint(0, 2**32 - 1)
        generator = torch.manual_seed(seed)

        prompt = stage_config.get("prompt", "")
        cn_type = stage_config.get("controlnet", "none")
        scale = float(stage_config.get("scale", 0.0))

        w, h = _Cfg.IMAGE_WIDTH, _Cfg.IMAGE_HEIGHT

        # 构造两路 ControlNet 的控制图和权重
        # 索引 0 → OpenPose，索引 1 → Canny
        blank = Image.new("RGB", (w, h), color=(255, 255, 255))

        if prev_image is None or cn_type == "none":
            control_images = [blank, blank]
            scales = [0.0, 0.0]
        elif cn_type == "openpose":
            control_images = [prev_image.convert("RGB").resize((w, h)), blank]
            scales = [scale, 0.0]
        else:  # canny (default for stages 2-4)
            control_images = [blank, prev_image.convert("RGB").resize((w, h))]
            scales = [0.0, scale]

        result = self._pipeline(
            prompt=prompt,
            image=control_images,
            controlnet_conditioning_scale=scales,
            num_inference_steps=_Cfg.NUM_INFERENCE_STEPS,
            guidance_scale=_Cfg.GUIDANCE_SCALE,
            generator=generator,
        )
        return result.images[0], seed


# 模块级单例，供其他模块直接导入使用
engine = ArtEngine()
