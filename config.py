# config.py
class Config:
    # !! 必须修改：请将 "123456789" 替换为你的真实 QQ 号，机器人才能私聊通知你 !!
    SUPERUSER_ID: str = "123456789"

    # ------------------------------------------------------------------
    # 定时任务时间窗口
    # ------------------------------------------------------------------
    # 任务仅在 [SCHEDULE_START_HOUR, SCHEDULE_END_HOUR] 闭区间内触发（24 小时制）
    SCHEDULE_START_HOUR: int = 8   # 上午 8 点开始
    SCHEDULE_END_HOUR: int = 23    # 晚上 11 点结束（不会在深夜打扰你）

    # ------------------------------------------------------------------
    # HuggingFace 镜像加速
    # ------------------------------------------------------------------
    # 设为 True 时，engine.py 会在模块顶部将 HF_ENDPOINT 指向国内镜像站，
    # 解决大陆地区无法访问 huggingface.co 的问题。
    # 若已通过其他方式（代理/VPN）解决网络问题，可设为 False 使用官方源。
    HF_MIRROR: bool = True
    HF_ENDPOINT_MIRROR: str = "https://hf-mirror.com"
    HF_ENDPOINT_OFFICIAL: str = "https://huggingface.co"

    # ------------------------------------------------------------------
    # 模型配置
    # ------------------------------------------------------------------
    # Stable Diffusion 1.5 基础模型（HuggingFace Hub ID 或本地路径）
    SD_MODEL_ID: str = "runwayml/stable-diffusion-v1-5"
    # ControlNet：OpenPose（用于阶段 1 构图）
    OPENPOSE_CONTROLNET_ID: str = "lllyasviel/sd-controlnet-openpose"
    # ControlNet：Canny（用于阶段 2-4 精修）
    CANNY_CONTROLNET_ID: str = "lllyasviel/sd-controlnet-canny"

    # 如已手动下载模型，可填写本地目录路径（留空则自动从网络下载）
    # 支持绝对路径和相对于机器人启动目录的相对路径
    LOCAL_SD_PATH: str = ""
    LOCAL_OPENPOSE_PATH: str = ""
    LOCAL_CANNY_PATH: str = ""

    # ------------------------------------------------------------------
    # 图像生成参数
    # ------------------------------------------------------------------
    IMAGE_WIDTH: int = 512
    IMAGE_HEIGHT: int = 512
    NUM_INFERENCE_STEPS: int = 30
    GUIDANCE_SCALE: float = 7.5

    # ------------------------------------------------------------------
    # 数据路径
    # ------------------------------------------------------------------
    BASE_DATA_PATH: str = "data/ai_trainer"

    # ------------------------------------------------------------------
    # 四阶段绘画流水线定义
    # ------------------------------------------------------------------
    # 字段说明：
    #   name        - 阶段标识（同时作为训练数据子目录名）
    #   label       - 中文说明（用于消息推送）
    #   controlnet  - 使用的 ControlNet 类型："openpose" | "canny" | "none"
    #   scale       - ControlNet 权重；第一阶段无前序图，固定为 0.0
    #   prompt_template - 提示词模板，{subject} 将被替换为本次主题描述
    PIPELINE_STAGES: list = [
        {
            "name": "stage_1_composition",
            "label": "阶段1：构图（骨架/定位线）",
            "controlnet": "none",
            "scale": 0.0,
            "prompt_template": (
                "simple body skeleton, rough position lines, pose composition, "
                "{subject}, minimal detail, stick figure layout, pencil sketch"
            ),
        },
        {
            "name": "stage_2_lineart",
            "label": "阶段2：线稿细化",
            "controlnet": "canny",
            "scale": 0.8,
            "prompt_template": (
                "clean ink lineart, precise clean lines, {subject}, "
                "high detail linework, no color, finished line art"
            ),
        },
        {
            "name": "stage_3_coloring",
            "label": "阶段3：上色",
            "controlnet": "canny",
            "scale": 0.6,
            "prompt_template": (
                "flat colors, basic coloring, {subject}, "
                "anime flat shading, cell shading, vivid colors"
            ),
        },
        {
            "name": "stage_4_lighting",
            "label": "阶段4：光影完稿",
            "controlnet": "canny",
            "scale": 0.4,
            "prompt_template": (
                "volumetric lighting, ray tracing, dramatic shadows, highlights, "
                "rim light, {subject}, masterpiece, complete illustration"
            ),
        },
    ]

    # ------------------------------------------------------------------
    # 主题描述词池
    # ------------------------------------------------------------------
    # 调度器每次触发时从此池中随机选取一条作为本次创作主题。
    # 可按需自由增删条目。
    SUBJECT_POOL: list = [
        "1girl, long blue hair, maid outfit, smiling, indoor cafe background, anime style",
        "1girl, short black hair, school uniform, reading book, library background, anime style",
        "1boy, white spiky hair, casual hoodie, standing confidently, city street background, anime style",
        "1girl, twin tails, magical girl outfit, flying, starry night sky background, anime style",
        "1boy, brown hair, samurai armor, battle stance, misty forest background, anime style",
        "1girl, long pink hair, sundress, sitting by window, warm sunset background, anime style",
        "1girl, silver hair, gothic lolita outfit, holding umbrella, rainy street background, anime style",
        "1boy, dark hair, detective coat, looking mysterious, foggy alley background, anime style",
    ]
