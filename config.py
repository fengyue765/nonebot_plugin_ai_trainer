"""Configuration for nonebot_plugin_ai_trainer."""


class Config:
    # !! 必须修改：请替换为你的实际 QQ 号 !!
    SUPERUSER_ID: str = "3052246120"

    # ------------------------------------------------------------------
    # 后端服务地址
    # ------------------------------------------------------------------
    # ComfyUI API 地址（WebSocket 和 HTTP 均使用此基础地址）
    COMFY_URL: str = "127.0.0.1:8188"
    # Ollama API 地址
    OLLAMA_URL: str = "http://127.0.0.1:11434"
    # Ollama 使用的模型
    OLLAMA_MODEL: str = "dolphin-llama3:8b"
    # Ollama API 调用超时（秒）
    OLLAMA_TIMEOUT: int = 60

    # ------------------------------------------------------------------
    # 数据路径
    # ------------------------------------------------------------------
    DATA_ROOT: str = "data/ai_trainer"
    # Persona 数据文件路径
    PERSONA_FILE: str = "data/ai_trainer/personas.json"
    # 当前流水线状态文件路径
    PIPELINE_STATE_FILE: str = "data/ai_trainer/pipeline_state.json"

    # ------------------------------------------------------------------
    # 历史记录配置
    # ------------------------------------------------------------------
    # 历史记录根目录
    HISTORY_ROOT: str = "data/ai_trainer/history"
    # 评分对应的子目录名称
    SCORE_DIRS: dict = {
        1: "score_1",
        2: "score_2", 
        3: "score_3",
        4: "score_4",
        5: "score_5"
    }

    # ------------------------------------------------------------------
    # 提示词权重配置
    # ------------------------------------------------------------------
    CHARACTER_WEIGHT: float = 1.5      # 角色特征权重 (1.0-1.5)
    YURI_WEIGHT: float = 1.3           # 百合题材权重
    STYLE_WEIGHT: float = 1.1          # 二次元风格权重
    NSFW_INTENSITY: float = 1.0        # NSFW 题材强度 (0.0-1.0)

    # ------------------------------------------------------------------
    # 定时任务设置
    # ------------------------------------------------------------------
    # 每隔多少小时推进一次流水线步骤（推荐 2 小时）
    # SCHEDULER_INTERVAL_HOURS: int = 1
    # 任务允许运行的起始小时（含），24 小时制
    # SCHEDULER_START_HOUR: int = 8
    # 任务允许运行的结束小时（含），24 小时制
    # SCHEDULER_END_HOUR: int = 18

    # ------------------------------------------------------------------
    # 四阶段流水线步骤名称
    # ------------------------------------------------------------------
    """
    PIPELINE_STEPS: list = [
        "sketch",
        "lineart",
        "flat_color",
        "final_render",
    ]

    # 各步骤对应的中文标签
    PIPELINE_STEP_LABELS: dict = {
        "sketch": "草图",
        "lineart": "线稿",
        "flat_color": "底色",
        "final_render": "完稿",
    }
"""