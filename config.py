# config.py
class Config:
    # !! 必须修改：请替换为你的实际 QQ 号，否则机器人无法私聊你 !!
    SUPERUSER_ID = "123456789"

    # 数据路径
    BASE_DATA_PATH = "data/ai_trainer"

    # 生成图片的分辨率
    IMAGE_WIDTH = 512
    IMAGE_HEIGHT = 512

    # 模型 ID
    SD_MODEL_ID = "runwayml/stable-diffusion-v1-5"
    CONTROLNET_MODEL_ID = "lllyasviel/sd-controlnet-openpose"

    # 定时任务设置
    # 每隔多少分钟生成一次（建议 120-180 分钟）
    SCHEDULER_INTERVAL_MINUTES = 120
    # 任务允许运行的起始小时（含），24 小时制
    SCHEDULER_START_HOUR = 8    # 上午 8 点
    # 任务允许运行的结束小时（含），24 小时制
    # 设为 23 表示 23:xx 是最后一个允许的小时段（即不在 0-7 点凌晨运行）
    SCHEDULER_END_HOUR = 23     # 晚上 11 点（含 23:xx）
