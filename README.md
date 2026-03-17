# nonebot_plugin_ai_trainer

一个基于 **ComfyUI + Ollama** 的 NoneBot2 AI 绘画训练插件，实现"人在回路（Human-in-the-Loop）"四阶段绘画流水线。

---

## 功能概览

1. **风格学习**：发送参考图片，插件用 WD14 Tagger 自动提取标签并通过 Ollama 分析，生成一个"画风人格（Persona）"。
2. **四阶段绘画流水线**：草图 → 线稿 → 底色 → 完稿，每一步都通过 ComfyUI 后端生成。
3. **定时推进**：每隔 2 小时（8:00-23:00）自动推进当前步骤并发送给用户评分。
4. **交互评分**：用户回复 1-5 分，低分重画，高分推进到下一步。

---

## 目录结构

```
nonebot_plugin_ai_trainer/
├── __init__.py          # 插件入口，命令注册，定时任务
├── config.py            # 所有配置项
├── core/
│   ├── persona.py       # 画风人格管理
│   ├── prompts.py       # 提示词生成与 Ollama 优化
│   └── pipeline.py      # 四阶段流水线状态管理
├── backend/
│   └── comfy.py         # ComfyUI API 客户端
└── workflows/
    ├── workflow_step1.json      # Txt2Img（草图）
    ├── workflow_img2img.json    # Img2Img + Canny ControlNet（细化）
    └── workflow_tagger.json     # WD14 图片标签提取
```

---

## 环境要求

| 依赖 | 说明 |
|------|------|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 后端图像生成引擎（需本地部署） |
| [Ollama](https://ollama.ai) + `dolphin-llama3` | 提示词优化 & 风格分析 |
| `aiohttp` | 异步 HTTP/WebSocket 通信 |
| `nonebot-plugin-apscheduler` | NoneBot2 定时任务 |

```bash
pip install aiohttp nonebot-plugin-apscheduler
```

### ComfyUI 所需模型

将以下模型放入 ComfyUI 对应目录：

| 模型 | 路径 |
|------|------|
| SD 1.5（如 `v1-5-pruned-emaonly.safetensors`） | `ComfyUI/models/checkpoints/` |
| ControlNet Canny（`control_v11p_sd15_canny.pth`） | `ComfyUI/models/controlnet/` |
| WD14 Tagger（需安装 `ComfyUI-WD14-Tagger` 节点） | 节点自动管理 |

---

## 配置

编辑 `nonebot_plugin_ai_trainer/config.py`：

```python
class Config:
    SUPERUSER_ID: str = "YOUR_QQ_ID_HERE"   # !! 必须修改 !!

    COMFY_URL: str = "127.0.0.1:8188"       # ComfyUI 地址
    OLLAMA_URL: str = "http://127.0.0.1:11434"  # Ollama 地址
    OLLAMA_MODEL: str = "dolphin-llama3"    # Ollama 模型

    DATA_ROOT: str = "data/ai_trainer"

    SCHEDULER_INTERVAL_HOURS: int = 2       # 推进间隔（小时）
    SCHEDULER_START_HOUR: int = 8
    SCHEDULER_END_HOUR: int = 23
```

---

## 使用指南

### 命令列表

| 命令 | 说明 |
|------|------|
| `/learn <名称> [数量]` | 开始学习新风格，发送指定数量的参考图片 |
| `/use <名称>` | 切换当前活动风格 |
| `/list` | 列出所有已学习的风格 |
| `/draw <描述>` | 启动新的四阶段绘画流水线 |
| 回复评分 `1-5` | 对当前步骤打分（1-2=重做，3-5=继续） |

### 示例流程

```
# 1. 学习风格
/learn miyazaki 3
[发送3张宫崎骏风格的参考图]

# 2. 切换风格
/use miyazaki

# 3. 开始绘画
/draw 1girl, blue hair, maid outfit, anime style

# 机器人发来草图
> 步骤 1/4: 草图
> 请回复评分 1-5…

# 用户引用图片回复
4

# 机器人进入下一步…
```

---

## 数据存储

```
data/ai_trainer/
├── personas.json          # 已学习的风格人格
├── pipeline_state.json    # 当前流水线状态
└── pipeline/
    └── <user_id>/
        ├── sketch/
        ├── lineart/
        ├── flat_color/
        └── final_render/
```

---

## 工作流 JSON 说明

工作流文件存放于 `workflows/` 目录，可根据实际 ComfyUI 环境修改节点 ID 和参数：

- **`workflow_step1.json`**：纯文生图，生成初始草图。
- **`workflow_img2img.json`**：图生图 + Canny ControlNet，用于线稿、底色、完稿阶段。
- **`workflow_tagger.json`**：WD14 Tagger，用于分析参考图片标签。

> **提示**：如果你的 ComfyUI 中的 checkpoint 或 ControlNet 文件名与 JSON 中不同，请直接编辑对应 JSON 文件中的 `ckpt_name` / `control_net_name` 字段。
