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

    # 定时任务设置
    # 每隔多少分钟生成一次（建议 120-180 分钟）
    SCHEDULER_INTERVAL_MINUTES = 120
    # 任务允许运行的起始小时（含），24 小时制
    SCHEDULER_START_HOUR = 8    # 上午 8 点
    # 任务允许运行的结束小时（含），24 小时制
    # 设为 23 表示 23:xx 是最后一个允许的小时段（即不在 0-7 点凌晨运行）
    SCHEDULER_END_HOUR = 23     # 晚上 11 点（含 23:xx）
