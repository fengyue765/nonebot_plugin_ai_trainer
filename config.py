# config.py
class Config:
    # !! 必须修改：请替换为你的实际 QQ 号，否则机器人无法私聊你 !!
    SUPERUSER_ID = "123456789"

    # 数据路径
    BASE_DATA_PATH = "data/ai_trainer"

    # 生成图片的分辨率
    IMAGE_WIDTH = 512
    IMAGE_HEIGHT = 512

    # 模型 ID（从网络自动下载时使用）
    SD_MODEL_ID = "runwayml/stable-diffusion-v1-5"
    CONTROLNET_MODEL_ID = "lllyasviel/sd-controlnet-openpose"

    # 手动下载模型时的本地路径（留空则从网络下载）
    # 填写后将完全跳过网络，直接从本地磁盘加载，支持绝对路径和相对路径。
    # 示例：LOCAL_MODEL_PATH = "models/stable-diffusion-v1-5"
    LOCAL_MODEL_PATH: str = ""
    LOCAL_CONTROLNET_PATH: str = ""

    # ------------------------------------------------------------------
    # 绘画流水线步骤定义
    # ------------------------------------------------------------------
    # 每幅完整图由下列步骤依次生成，前一步的输出作为后一步的 ControlNet 条件输入。
    # 各字段说明：
    #   name                         - 步骤标识（同时作为训练数据目录名）
    #   label                        - 中文说明（用于消息推送）
    #   prompt_template              - 提示词模板，{subject} 会被替换为当前主题描述
    #   controlnet_conditioning_scale - ControlNet 权重（第一步无前序图，固定为 0.0）
    PIPELINE_STEPS: list[dict] = [
        {
            "name": "step_1_skeleton",
            "label": "第一草图（骨架/定位线）",
            "prompt_template": (
                "simple body skeleton, rough position lines, pose composition, "
                "{subject}, minimal detail, stick figure layout, pencil sketch"
            ),
            "controlnet_conditioning_scale": 0.0,
        },
        {
            "name": "step_2_rough_sketch",
            "label": "第二草图（外貌/背景轮廓）",
            "prompt_template": (
                "rough sketch, basic hairstyle, clothing silhouette, background outline, "
                "{subject}, loose messy lines"
            ),
            "controlnet_conditioning_scale": 0.7,
        },
        {
            "name": "step_3_detailed_sketch",
            "label": "第三草图（细化）",
            "prompt_template": (
                "detailed pencil sketch, refined shapes, facial features, clothing details, "
                "{subject}, refined lines"
            ),
            "controlnet_conditioning_scale": 0.8,
        },
        {
            "name": "step_4_lineart",
            "label": "线稿",
            "prompt_template": (
                "clean ink lineart, precise clean lines, {subject}, "
                "high detail linework, no color, finished line art"
            ),
            "controlnet_conditioning_scale": 0.9,
        },
        {
            "name": "step_5_base_color",
            "label": "上底色（大色块）",
            "prompt_template": (
                "flat base colors, large color blocks, {subject}, "
                "simple coloring, anime flat shading"
            ),
            "controlnet_conditioning_scale": 0.8,
        },
        {
            "name": "step_6_refined_color",
            "label": "细化色块（小色块）",
            "prompt_template": (
                "refined color areas, detailed smaller color blocks, "
                "{subject}, clean anime coloring"
            ),
            "controlnet_conditioning_scale": 0.7,
        },
        {
            "name": "step_7_color_blend",
            "label": "调色（减少色块感）",
            "prompt_template": (
                "smooth color blending, soft gradients, unified palette, "
                "{subject}, less blocky, polished colors"
            ),
            "controlnet_conditioning_scale": 0.6,
        },
        {
            "name": "step_8_lighting",
            "label": "光影效果（完稿）",
            "prompt_template": (
                "lighting and shadows, highlights, rim light, shading, "
                "{subject}, complete illustration, masterpiece quality"
            ),
            "controlnet_conditioning_scale": 0.5,
        },
    ]

    # ------------------------------------------------------------------
    # 主题描述词池
    # ------------------------------------------------------------------
    # 调度器每次触发时从此池中随机选取一条，作为"最终成品图的要求"。
    # 该描述会被自动注入到 PIPELINE_STEPS 各步骤的 prompt_template，
    # 无需手动为每个步骤单独编写 prompt。
    # 可按需自由增删条目。
    SUBJECT_POOL: list[str] = [
        "1girl, long blue hair, maid outfit, smiling, indoor cafe background, anime style",
        "1girl, short black hair, school uniform, reading book, library background, anime style",
        "1boy, white spiky hair, casual hoodie, standing confidently, city street background, anime style",
        "1girl, twin tails, magical girl outfit, flying, starry night sky background, anime style",
        "1boy, brown hair, samurai armor, battle stance, misty forest background, anime style",
        "1girl, long pink hair, sundress, sitting by window, warm sunset background, anime style",
        "1girl, silver hair, gothic lolita outfit, holding umbrella, rainy street background, anime style",
        "1boy, dark hair, detective coat, looking mysterious, foggy alley background, anime style",
    ]

    # 定时任务设置
    # 每隔多少分钟生成一次（建议 120-180 分钟）
    SCHEDULER_INTERVAL_MINUTES = 120
    # 任务允许运行的起始小时（含），24 小时制
    SCHEDULER_START_HOUR = 8    # 上午 8 点
    # 任务允许运行的结束小时（含），24 小时制
    # 设为 23 表示 23:xx 是最后一个允许的小时段（即不在 0-7 点凌晨运行）
    SCHEDULER_END_HOUR = 23     # 晚上 11 点（含 23:xx）
