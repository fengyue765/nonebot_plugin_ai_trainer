# manager.py
"""数据管理模块：负责待审核图片的保存、归档和丢弃。"""

import json
import os
import shutil
from pathlib import Path

from .config import Config
from .utils import make_file_id


class DataManager:
    """管理训练数据的目录结构和元数据文件。

    目录结构::

        data/ai_trainer/
        ├── pending/          # 待用户审核的图片（临时目录）
        │   ├── stage_1_composition/
        │   ├── stage_2_lineart/
        │   ├── stage_3_coloring/
        │   └── stage_4_lighting/
        ├── train/            # 用户批准的训练数据
        │   ├── stage_1_composition/
        │   ├── ...
        │   └── metadata.jsonl   # HuggingFace datasets 兼容格式
        └── rejected/         # 用户拒绝的图片（保留供分析）
    """

    def __init__(self, base_path: str = Config.BASE_DATA_PATH) -> None:
        self.base_path = Path(base_path)
        self.pending_dir = self.base_path / "pending"
        self.train_dir = self.base_path / "train"
        self.reject_dir = self.base_path / "rejected"
        self._init_folders()

    def _init_folders(self) -> None:
        """按 Config.PIPELINE_STAGES 自动创建所有需要的子目录。"""
        for stage in Config.PIPELINE_STAGES:
            (self.pending_dir / stage["name"]).mkdir(parents=True, exist_ok=True)
            (self.train_dir / stage["name"]).mkdir(parents=True, exist_ok=True)
        self.reject_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def save_pending(self, image, stage_name: str, metadata: dict) -> str:
        """保存图片和元数据到待审核目录。

        Args:
            image:      PIL.Image 对象。
            stage_name: 流水线阶段名称，对应 Config.PIPELINE_STAGES[i]["name"]。
            metadata:   包含 prompt、seed 等信息的字典，会序列化为 JSON 文件。

        Returns:
            保存后的图片文件路径（字符串），可作为后续 approve/reject 的参数。
        """
        file_id = make_file_id(metadata.get("seed", 0))
        save_dir = self.pending_dir / stage_name
        save_dir.mkdir(parents=True, exist_ok=True)

        img_path = save_dir / f"{file_id}.png"
        meta_path = save_dir / f"{file_id}.json"

        image.save(img_path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return str(img_path)

    def approve_data(self, pending_path: str) -> tuple[bool, str]:
        """将待审核图片归档至训练集，并追加记录到 metadata.jsonl。

        Args:
            pending_path: ``save_pending`` 返回的图片文件路径。

        Returns:
            ``(success, message)`` 元组。
        """
        src_img = Path(pending_path)
        src_meta = src_img.with_suffix(".json")

        if not src_img.exists():
            return False, "文件已过期或不存在"

        stage_name = src_img.parent.name
        dest_dir = self.train_dir / stage_name
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_img = dest_dir / src_img.name
        dest_meta = dest_dir / src_meta.name

        shutil.move(str(src_img), str(dest_img))
        if src_meta.exists():
            shutil.move(str(src_meta), str(dest_meta))

        # 追加到 metadata.jsonl（HuggingFace datasets 兼容格式）
        jsonl_path = self.train_dir / "metadata.jsonl"
        meta: dict = {}
        if dest_meta.exists():
            with open(dest_meta, "r", encoding="utf-8") as f:
                meta = json.load(f)

        record = {
            "file_name": f"{stage_name}/{src_img.name}",
            "text": meta.get("prompt", ""),
            "seed": meta.get("seed", 0),
            "stage": stage_name,
            "subject": meta.get("subject", ""),
            "rating": meta.get("rating", 5),
            "control_params": meta.get("control_params", {}),
        }
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return True, f"已归档至 {stage_name}，样本库 +1 📁"

    def reject_data(self, pending_path: str) -> tuple[bool, str]:
        """将待审核图片移入 rejected 目录（元数据同时丢弃）。

        Args:
            pending_path: ``save_pending`` 返回的图片文件路径。

        Returns:
            ``(success, message)`` 元组。
        """
        src_img = Path(pending_path)
        src_meta = src_img.with_suffix(".json")

        if src_img.exists():
            shutil.move(str(src_img), str(self.reject_dir / src_img.name))
        if src_meta.exists():
            os.remove(src_meta)

        return True, "已丢弃 🗑️"


# 模块级单例，供其他模块直接导入
data_manager = DataManager()
