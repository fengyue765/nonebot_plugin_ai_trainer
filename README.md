# nonebot_plugin_ai_trainer

一个基于 NoneBot2 的 **AI 绘画训练数据采集插件**，采用「人在回路（Human-in-the-Loop）」工作流。

插件通过定时任务自动生成图片，以 **4 阶段流水线**（构图 → 线稿 → 上色 → 光影）逐步精修，每个阶段结束后等待用户评分（1-5 分）。低分（1-2 分）触发重做，高分（3-5 分）归档并推进下一阶段。所有数据自动整理为 HuggingFace `datasets` 兼容格式，为后续强化学习（RL）奠定数据基础。

---

## 整体流程

```
定时任务 / /画画 命令
         ↓
  阶段1：构图（骨架/定位线）
         ↓ 发送给用户
  用户评分 1-5
  ├─ 1-2分 → 重新生成本阶段
  └─ 3-5分 → 归档 → 阶段2：线稿细化
                         ↓ 发送给用户
                   用户评分 1-5
                   ├─ 1-2分 → 重新生成本阶段
                   └─ 3-5分 → 归档 → 阶段3：上色
                                          ↓ ...
                                    阶段4：光影完稿
                                          ↓
                                    🎉 流水线完成
```

---

## 安装

### 1. 安装依赖

```bash
# PyTorch（根据你的 CUDA 版本选择，以 CUDA 12.1 为例）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 其他依赖
pip install diffusers transformers accelerate controlnet_aux Pillow nonebot-plugin-apscheduler
```

> **CUDA 版本对照**：访问 https://pytorch.org/get-started/locally/ 选择适合你系统的安装命令。

### 2. 加载插件

在你的 NoneBot2 项目的 `pyproject.toml` 或 `bot.py` 中加载插件：

```toml
# pyproject.toml
[tool.nonebot]
plugins = ["nonebot_plugin_ai_trainer"]
```

或在 `bot.py` 中：

```python
nonebot.load_plugin("nonebot_plugin_ai_trainer")
```

---

## 配置

所有配置项均位于 `nonebot_plugin_ai_trainer/config.py`，无需修改 `.env` 文件。

### 必须修改的配置

打开 `config.py`，找到以下行并替换为你的 QQ 号：

```python
SUPERUSER_ID: str = "123456789"  # ← 改为你的真实 QQ 号
```

### 完整配置说明

```python
class Config:
    # !! 必须修改 !!
    SUPERUSER_ID: str = "123456789"

    # 定时任务时间窗口（24 小时制）
    SCHEDULE_START_HOUR: int = 8   # 上午 8 点开始
    SCHEDULE_END_HOUR: int = 23    # 晚上 11 点结束

    # HuggingFace 镜像（True = 使用国内 hf-mirror.com，解决大陆访问问题）
    HF_MIRROR: bool = True

    # 模型（首次启动自动下载，约 5-8 GB）
    SD_MODEL_ID: str = "runwayml/stable-diffusion-v1-5"
    OPENPOSE_CONTROLNET_ID: str = "lllyasviel/sd-controlnet-openpose"
    CANNY_CONTROLNET_ID: str = "lllyasviel/sd-controlnet-canny"

    # 手动下载后的本地路径（留空 = 自动从网络下载）
    LOCAL_SD_PATH: str = ""
    LOCAL_OPENPOSE_PATH: str = ""
    LOCAL_CANNY_PATH: str = ""

    # 图像分辨率
    IMAGE_WIDTH: int = 512
    IMAGE_HEIGHT: int = 512

    # 数据存储根目录
    BASE_DATA_PATH: str = "data/ai_trainer"

    # 主题描述词池（每次触发随机选取一条）
    SUBJECT_POOL: list = [
        "1girl, long blue hair, maid outfit, smiling, indoor cafe background, anime style",
        # 可按需增删...
    ]
```

| 配置项 | 说明 |
|--------|------|
| `SUPERUSER_ID` | **必须修改**。填入你自己的 QQ 号，机器人会把生成图片以私信发给你。 |
| `SCHEDULE_START_HOUR` | 定时任务最早触发时间（默认 `8`，即上午 8 点）。 |
| `SCHEDULE_END_HOUR` | 定时任务最晚触发时间（默认 `23`，即晚上 11 点，不会深夜打扰）。 |
| `HF_MIRROR` | 设为 `True` 时使用 `hf-mirror.com` 镜像站，解决大陆下载问题（**推荐开启**）。 |
| `LOCAL_SD_PATH` | SD 1.5 模型的本地目录路径。填写后完全离线加载，跳过网络下载。 |
| `LOCAL_OPENPOSE_PATH` | OpenPose ControlNet 模型的本地目录路径。 |
| `LOCAL_CANNY_PATH` | Canny ControlNet 模型的本地目录路径。 |
| `SUBJECT_POOL` | 主题描述词池。每条描述代表一幅完整成品图的创作要求，系统自动分解到各阶段 prompt 中。 |
| `PIPELINE_STAGES` | 四阶段流水线定义（高级）。一般无需修改，如需调整各阶段的 prompt 模板或 ControlNet 权重，可直接编辑。 |

---

## 使用指南

### 自动训练模式（定时任务）

启动 NoneBot2 后，插件会在每天 **上午 8 点到晚上 11 点**之间，每隔 **3 小时**自动触发一次绘画流水线，无需任何手动操作。

**工作流程：**

1. 机器人从 `SUBJECT_POOL` 随机选取一条主题描述。
2. 生成**阶段 1（构图）** 图片，以私信形式发送给你。
3. 你**引用（回复）**该图片并发送评分（1-5 分）。
4. 根据评分：
   - **1-2 分** → 机器人重新生成本阶段（使用新随机种子）。
   - **3-5 分** → 机器人归档图片并自动生成**阶段 2（线稿）**。
5. 重复步骤 3-4，直到全部 4 个阶段完成。

**私信示例：**

```
[AI训练师] 阶段1：构图（骨架/定位线） (1/4)
主题：1girl, long blue hair, maid outfit, smiling, indoor cafe background, anime style
Prompt：simple body skeleton, rough position lines, pose composition, 1girl, long blue hair...

请引用本条消息回复评分（1-5 分）：
  1-2 分 → 重新生成本阶段
  3-5 分 → 归档并进入下一阶段
也可直接回复 ok（相当于5分）或 pass（相当于1分）
[图片]

你的回复：引用上图，发送 "4"

机器人回复：✅ 4 分，已归档至 stage_1_composition，样本库 +1 📁
（随即发送阶段2图片）
```

### 手动触发（/画画）

你可以随时私聊机器人，手动触发一次完整的 4 阶段流水线：

```
/画画 [主题描述（可选）]
```

**示例：**

```
# 指定主题
/画画 1girl, silver hair, gothic lolita outfit, rainy street background, anime style

# 不指定主题（随机从 SUBJECT_POOL 选取）
/画画
```

### 命令速查表

| 命令 | 别名 | 使用方式 | 效果 |
|------|------|----------|------|
| `1` ~ `5` | — | 引用回复机器人图片 | 按分数处理：1-2分重做，3-5分归档并推进 |
| `ok` | `保存`、`不错` | 引用回复机器人图片 | 相当于 5 分，归档并推进 |
| `pass` | `丢弃`、`不行` | 引用回复机器人图片 | 相当于 1 分，丢弃并重做 |
| `/paint` | `/画画`、`/绘画` | 直接发送（可附主题描述） | 手动触发一次完整流水线 |

> ⚠️ **注意**：`1`~`5`、`ok`、`pass` 命令必须以**引用回复**的方式使用，直接发送无效。

---

## 四阶段流水线详解

| 阶段 | 名称 | ControlNet | 说明 |
|------|------|-----------|------|
| 1 | `stage_1_composition` | 无（纯 txt2img） | 生成人体骨架/定位线草图，确定姿势和构图 |
| 2 | `stage_2_lineart` | Canny（权重 0.8） | 以阶段 1 为参考，生成精细线稿 |
| 3 | `stage_3_coloring` | Canny（权重 0.6） | 以阶段 2 为参考，添加平面上色 |
| 4 | `stage_4_lighting` | Canny（权重 0.4） | 以阶段 3 为参考，添加光影效果，完成创作 |

---

## 数据输出

所有训练数据存放在 `data/ai_trainer/` 目录下：

```
data/ai_trainer/
├── pending/                    # 待审核图片（临时）
│   ├── stage_1_composition/
│   ├── stage_2_lineart/
│   ├── stage_3_coloring/
│   └── stage_4_lighting/
├── train/                      # 已批准的训练数据 ✅
│   ├── stage_1_composition/
│   ├── stage_2_lineart/
│   ├── stage_3_coloring/
│   ├── stage_4_lighting/
│   └── metadata.jsonl          # HuggingFace datasets 兼容格式
└── rejected/                   # 已拒绝的图片（低分重做后产生）
```

### `metadata.jsonl` 格式

每条记录为一行 JSON，可直接用 `datasets` 库加载：

```jsonl
{"file_name": "stage_2_lineart/1718000000_123456789.png", "text": "clean ink lineart, ...", "seed": 123456789, "stage": "stage_2_lineart", "subject": "1girl, blue hair...", "rating": 4, "control_params": {}}
```

**加载示例：**

```python
from datasets import load_dataset
ds = load_dataset("imagefolder", data_dir="data/ai_trainer/train")
```

---

## 首次启动：模型下载

首次运行时，插件会**自动**从 HuggingFace 下载以下模型（合计约 7-9 GB）：

| 模型 | 大小 | 用途 |
|------|------|------|
| `runwayml/stable-diffusion-v1-5` | ~4 GB | 图像生成基础模型 |
| `lllyasviel/sd-controlnet-openpose` | ~1.5 GB | 阶段 1 构图控制 |
| `lllyasviel/sd-controlnet-canny` | ~1.5 GB | 阶段 2-4 精修控制 |

下载完成后模型会缓存至本地（通常在 `~/.cache/huggingface/hub/`），后续启动**不会重复下载**。

插件内置了以下下载加速策略（**无需手动配置**）：

1. **首选 hf-mirror.com 镜像站**：设置 `HF_MIRROR = True`（默认），自动使用国内镜像加速。
2. **自动切换端点**：镜像站失败时，自动重试官方源（带指数退避重试机制）。

### 手动下载模型（网络受限时）

如果自动下载仍然失败，可手动下载后配置本地路径：

#### 方法一：huggingface-cli（推荐）

```bash
pip install -U huggingface_hub

# 下载 SD 1.5（约 4 GB）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download \
    runwayml/stable-diffusion-v1-5 \
    --local-dir models/stable-diffusion-v1-5

# 下载 ControlNet OpenPose（约 1.5 GB）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download \
    lllyasviel/sd-controlnet-openpose \
    --local-dir models/sd-controlnet-openpose

# 下载 ControlNet Canny（约 1.5 GB）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download \
    lllyasviel/sd-controlnet-canny \
    --local-dir models/sd-controlnet-canny
```

> **Windows 用户（PowerShell）：**
> ```powershell
> $env:HF_ENDPOINT = "https://hf-mirror.com"
> huggingface-cli download runwayml/stable-diffusion-v1-5 --local-dir models/stable-diffusion-v1-5
> huggingface-cli download lllyasviel/sd-controlnet-openpose --local-dir models/sd-controlnet-openpose
> huggingface-cli download lllyasviel/sd-controlnet-canny --local-dir models/sd-controlnet-canny
> ```

#### 方法二：hfd.sh 脚本（多线程，速度最快）

```bash
# 下载脚本
wget https://hf-mirror.com/hfd/hfd.sh
chmod a+x hfd.sh

# 多线程下载（-x 4 表示 4 个线程）
./hfd.sh runwayml/stable-diffusion-v1-5 --tool aria2c -x 4
./hfd.sh lllyasviel/sd-controlnet-openpose --tool aria2c -x 4
./hfd.sh lllyasviel/sd-controlnet-canny --tool aria2c -x 4
```

#### 配置本地路径

下载完成后，在 `config.py` 中填写本地路径：

```python
LOCAL_SD_PATH = "models/stable-diffusion-v1-5"
LOCAL_OPENPOSE_PATH = "models/sd-controlnet-openpose"
LOCAL_CANNY_PATH = "models/sd-controlnet-canny"
```

填写后重启机器人，插件将**完全离线**加载模型，无需任何网络连接。

---

## 硬件要求

| 配置 | 显存 | 说明 |
|------|------|------|
| 最低可运行 | 4-6 GB | 开启 CPU Offload，速度较慢（每张图约 2-5 分钟） |
| 推荐配置 | **16 GB** | 流畅运行，每张图约 30-60 秒 |

插件默认调用 `pipeline.enable_model_cpu_offload()`，将模型子组件（UNet、VAE、文本编码器）按需在 CPU 与 GPU 之间调度，4-6 GB 显存的显卡也可运行，但速度会明显慢于 16 GB 配置。

---

## 常见问题

**Q：首次启动机器人长时间无响应？**  
A：正在下载 7-9 GB 的模型文件。请耐心等待，日志中会打印下载进度。可以观察 `~/.cache/huggingface/hub/` 目录的增长情况。

**Q：下载失败，提示网络错误？**  
A：请参照【手动下载模型】章节，先手动下载后配置本地路径。

**Q：评分命令没有响应？**  
A：请确认你是以**引用回复**的方式发送评分（长按消息 → 引用 → 发送数字），而不是直接发送数字。

**Q：想修改流水线步骤的 prompt？**  
A：编辑 `config.py` 中的 `PIPELINE_STAGES` 列表，修改对应阶段的 `prompt_template`。`{subject}` 占位符会在运行时被替换为本次选取的主题描述。

**Q：如何增加主题描述？**  
A：在 `config.py` 的 `SUBJECT_POOL` 列表中添加新条目即可。
