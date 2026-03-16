# nonebot_plugin_ai_trainer

一个用于 **AI 绘画训练数据采集** 的 NoneBot2 插件，采用"人在回路（Human-in-the-Loop）"工作流。  
插件通过定时任务自动生成候选图片，并以私聊消息的形式推送给超级用户，由用户通过交互命令审核标注，被批准的图片将自动保存为标准训练数据集。

---

## 安装

### 依赖

| 包名 | 说明 |
|------|------|
| `torch` | PyTorch 深度学习框架 |
| `diffusers` | Hugging Face 扩散模型库 |
| `controlnet_aux` | ControlNet 预处理器集合 |
| `Pillow` | 图像处理 |
| `nonebot-plugin-apscheduler` | NoneBot2 定时任务支持 |

```bash
pip install torch diffusers controlnet_aux Pillow nonebot-plugin-apscheduler
```

> **注意：** 首次运行时插件会自动从 Hugging Face 下载模型权重，视网络环境可能需要较长时间，请耐心等待。

---

## 配置

所有配置项均位于 `nonebot_plugin_ai_trainer/config.py`：

```python
class Config:
    # !! 必须修改：请替换为你的实际 QQ 号，否则机器人无法私聊你 !!
    SUPERUSER_ID = "YOUR_QQ_ID_HERE"

    # 数据路径
    BASE_DATA_PATH = "data/ai_trainer"

    # 生成图片的分辨率
    IMAGE_WIDTH = 512
    IMAGE_HEIGHT = 512

    # 模型 ID（SD 1.5 系列）
    SD_MODEL_ID = "runwayml/stable-diffusion-v1-5"
    CONTROLNET_MODEL_ID = "lllyasviel/sd-controlnet-openpose"

    # 定时任务设置
    SCHEDULER_INTERVAL_MINUTES = 120  # 每隔多少分钟生成一次
    SCHEDULER_START_HOUR = 8          # 任务允许运行的起始小时（含）
    SCHEDULER_END_HOUR = 23           # 任务允许运行的结束小时（含）
```

### 关键配置说明

| 配置项 | 说明 |
|--------|------|
| `SUPERUSER_ID` | **必须修改**。填入你自己的 QQ 号，机器人会将生成的图片私聊发给你。 |
| `SCHEDULER_START_HOUR` | 定时任务允许运行的最早小时（24 小时制，默认 `8`，即上午 8 点）。 |
| `SCHEDULER_END_HOUR` | 定时任务允许运行的最晚小时（24 小时制，默认 `23`，即晚上 11 点）。 |
| `SCHEDULER_INTERVAL_MINUTES` | 相邻两次自动生成的间隔分钟数（默认 `120`，即 2 小时）。 |
| `SD_MODEL_ID` | Stable Diffusion 1.5 基础模型 ID，可在 [Hugging Face](https://huggingface.co/models?pipeline_tag=text-to-image) 搜索同架构模型进行替换。 |
| `CONTROLNET_MODEL_ID` | ControlNet 模型 ID，默认使用 OpenPose 姿态控制模型。 |
| `LOCAL_MODEL_PATH` | SD 模型的**本地目录路径**。填写后直接从磁盘加载，完全跳过网络下载。留空则使用 `SD_MODEL_ID` 自动下载。 |
| `LOCAL_CONTROLNET_PATH` | ControlNet 模型的**本地目录路径**。含义同上。 |

---

## 使用指南

### 自动训练（定时任务）

插件启动后会按 `SCHEDULER_INTERVAL_MINUTES` 设定的间隔自动触发，**仅在 `SCHEDULER_START_HOUR`（含）到 `SCHEDULER_END_HOUR`（含）之间运行**（默认 8:00–23:00），不会在深夜打扰你。

每次触发时，机器人会：
1. 从预设任务列表中随机选取一个绘画任务（骨架、草图、线稿、上色等）。
2. 调用 AI 引擎生成图片。
3. 以私聊消息的形式将图片推送给 `SUPERUSER_ID` 指定的用户。

收到图片后，**引用（回复）该图片消息**并发送以下命令进行标注：

| 命令 | 别名 | 效果 |
|------|------|------|
| `ok` | `不错`、`保存` | ✅ 批准并归档至训练集，自动追加 `metadata.jsonl` |
| `pass` | `不行`、`丢弃` | 🗑️ 拒绝，图片移入 rejected 目录 |

> **注意：** 必须以**引用回复**的方式操作，直接发送命令无效。

示例流程：
```
[机器人私聊]
[碎片时间标注]
任务: step_3_lineart
Prompt: clean lineart, 1girl, detailed clothing
[图片]
回复 [ok] 归档，回复 [pass] 丢弃

[用户引用上图回复]
ok

[机器人回复]
✅ 已归档至 step_3_lineart，样本库+1
```

### 手动绘画

通过以下命令手动触发 AI 绘画并进行交互式精修：

```
/画画 [prompt]
/绘画 [prompt]
```

例如：
```
/画画 1girl, blue hair, anime style, clean lineart
```

交互式精修选项：

| 回复 | 效果 |
|------|------|
| `1` | ✅ 满意，进入下一步骤 |
| `2` | 🔄 重新生成（使用新随机种子） |
| `3` | 🎨 精修（保留本次种子，微调参数后重绘） |

---

## 数据输出

所有数据存放在 `data/ai_trainer/` 目录下：

```
data/ai_trainer/
├── pending/                  # 待审核图片（临时目录）
│   ├── step_1_skeleton/
│   ├── step_2_sketch/
│   ├── step_3_lineart/
│   └── step_4_color/
├── train/                    # 已批准的训练数据
│   ├── step_1_skeleton/
│   ├── step_2_sketch/
│   ├── step_3_lineart/
│   ├── step_4_color/
│   ├── step_5_finish/
│   └── metadata.jsonl        # HuggingFace 兼容格式元数据
└── rejected/                 # 已拒绝的图片
```

### `metadata.jsonl` 格式

每条记录为一行 JSON，兼容 HuggingFace `datasets` 库直接加载：

```jsonl
{"file_name": "step_3_lineart/1718000000_123456789.png", "text": "clean lineart, 1girl, detailed clothing", "seed": 123456789, "control_params": {}}
{"file_name": "step_4_color/1718003600_987654321.png", "text": "flat color, anime, 1girl, blue hair", "seed": 987654321, "control_params": {}}
```

---

## 常见问题

### 首次启动时机器人长时间无响应

首次运行时，插件会自动从 Hugging Face Hub 下载 Stable Diffusion 1.5 及 ControlNet 模型权重（合计约 **5–8 GB**），视网络环境可能需要数分钟至数十分钟。下载完成后模型会缓存至本地，后续启动不会重复下载。

插件会依次尝试以下下载策略，无需任何手动配置：

1. **hf-mirror.com 镜像站**（每个端点最多重试 3 次，带退避等待）
2. **huggingface.co 官方站**（同样重试 3 次）

若两个端点均失败，会在日志中打印明确的错误信息并指引手动下载。

---

### 手动下载模型（网络受限时）

如果自动下载仍然失败，可以通过以下任一方式手动下载模型，并在 `config.py` 中配置本地路径。

#### 方法一：使用 huggingface-cli（推荐）

```bash
pip install -U huggingface_hub

# 下载 SD 1.5 基础模型（约 4 GB）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download \
    runwayml/stable-diffusion-v1-5 \
    --local-dir models/stable-diffusion-v1-5

# 下载 ControlNet OpenPose 模型（约 1.5 GB）
HF_ENDPOINT=https://hf-mirror.com huggingface-cli download \
    lllyasviel/sd-controlnet-openpose \
    --local-dir models/sd-controlnet-openpose
```

> **Windows 用户：** PowerShell 中使用以下等效命令（分两条执行）：
> ```powershell
> $env:HF_ENDPOINT = "https://hf-mirror.com"
> huggingface-cli download runwayml/stable-diffusion-v1-5 --local-dir models/stable-diffusion-v1-5
> ```
> 或在 CMD 中：
> ```cmd
> set HF_ENDPOINT=https://hf-mirror.com
> huggingface-cli download runwayml/stable-diffusion-v1-5 --local-dir models/stable-diffusion-v1-5
> ```

#### 方法二：使用 git-lfs

```bash
# 前提：已安装 Git LFS（https://git-lfs.github.com）
git lfs install

# 克隆镜像仓库
git clone https://hf-mirror.com/runwayml/stable-diffusion-v1-5 models/stable-diffusion-v1-5
git clone https://hf-mirror.com/lllyasviel/sd-controlnet-openpose models/sd-controlnet-openpose
```

#### 配置本地路径

将下载好的模型目录路径填入 `config.py`：

```python
# 支持绝对路径和相对路径（相对于机器人运行目录）
LOCAL_MODEL_PATH = "models/stable-diffusion-v1-5"
LOCAL_CONTROLNET_PATH = "models/sd-controlnet-openpose"
```

填写后重启机器人，插件将直接从本地磁盘加载，完全绕过网络。

### 显存要求

| 配置 | 说明 |
|------|------|
| 最低可运行 | 约 4–6 GB 显存（纯推理，模型分块加载） |
| 推荐配置 | **16 GB 显存**（流畅运行，无性能瓶颈） |

插件在 `engine.py` 中默认调用 `pipeline.enable_model_cpu_offload()`，将 UNet、VAE、文本编码器等子组件按需在 CPU 与 GPU 之间调度，避免模型常驻显存。这使得 4–6 GB 显存的显卡也能运行，但每次推理都有额外的 CPU↔GPU 数据迁移开销，速度较慢。**推荐使用 16 GB 显存**，可在单次推理中将主要组件常驻 GPU，显著提升生成速度。
