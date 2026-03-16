# manager.py
import os
import json
import shutil
from datetime import datetime
from pathlib import Path

class DataManager:
    def __init__(self, base_path="data/ai_trainer"):
        self.base_path = Path(base_path)
        self.pending_dir = self.base_path / "pending"
        self.train_dir = self.base_path / "train"
        self.reject_dir = self.base_path / "rejected"
        self._init_folders()

    def _init_folders(self):
        """AI自动创建数据集目录结构"""
        for step in ["step_1_skeleton", "step_2_sketch", "step_3_lineart", "step_4_color", "step_5_finish"]:
            (self.train_dir / step).mkdir(parents=True, exist_ok=True)
            (self.pending_dir / step).mkdir(parents=True, exist_ok=True)
        self.reject_dir.mkdir(parents=True, exist_ok=True)

    def save_pending(self, image, step_name, metadata):
        """保存待审核图片"""
        file_id = f"{int(datetime.now().timestamp())}_{metadata['seed']}"
        filename = f"{file_id}.png"
        meta_filename = f"{file_id}.json"
        
        save_dir = self.pending_dir / step_name
        
        # 保存图片
        image.save(save_dir / filename)
        # 保存元数据
        with open(save_dir / meta_filename, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
            
        return str(save_dir / filename) # 返回唯一标识路径

    def approve_data(self, pending_path):
        """数据沉淀：将待审核图片移动到训练集，并追加metadata"""
        src_img = Path(pending_path)
        src_meta = src_img.with_suffix(".json")
        
        if not src_img.exists():
            return False, "文件已过期或不存在"

        # 解析路径获取步骤名 (pending/step_x/xxx.png)
        step_name = src_img.parent.name
        dest_dir = self.train_dir / step_name
        
        # 移动文件
        shutil.move(src_img, dest_dir / src_img.name)
        shutil.move(src_meta, dest_dir / src_meta.name)
        
        # 核心：自动追加到 metadata.jsonl (HuggingFace 格式)
        jsonl_path = self.train_dir / "metadata.jsonl"
        with open(jsonl_path, "a", encoding="utf-8") as f:
            # 读取刚才移动的meta
            with open(dest_dir / src_meta.name, 'r') as mf:
                meta = json.load(mf)
            
            record = {
                "file_name": f"{step_name}/{src_img.name}",
                "text": meta["prompt"],
                "seed": meta["seed"],
                "control_params": meta.get("control_params", {})
            }
            f.write(json.dumps(record) + "\n")
            
        return True, f"已归档至 {step_name}，样本库+1"

    def reject_data(self, pending_path):
        """丢弃数据"""
        src_img = Path(pending_path)
        src_meta = src_img.with_suffix(".json")
        if src_img.exists():
            shutil.move(src_img, self.reject_dir / src_img.name)
            if src_meta.exists():
                os.remove(src_meta) # 元数据直接删，没用了
        return True, "已丢弃"

data_manager = DataManager()
