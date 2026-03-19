"""Pipeline state manager with history tracking."""

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

from ..config import Config


@dataclass
class GenerationHistory:
    """Record of a single generation with its metadata."""
    timestamp: float
    user_id: str
    prompt: str  # 原始用户输入
    final_positive: str  # 最终使用的正面词
    final_negative: str  # 最终使用的负面词
    persona_name: Optional[str] = None  # 使用的风格名称
    score: Optional[int] = None  # 用户评分
    image_path: Optional[str] = None  # 图片存储路径
    model: str = "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"  # 使用的模型
    
    @property
    def datetime_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%Y%m%d_%H%M%S")
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> "GenerationHistory":
        return cls(**d)


@dataclass
class GenerationState:
    """Current generation state."""
    user_id: str
    prompt: str
    history_id: Optional[str] = None  # 关联的历史记录ID
    image_path: Optional[str] = None
    active: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GenerationState":
        return cls(
            user_id=d["user_id"],
            prompt=d["prompt"],
            history_id=d.get("history_id"),
            image_path=d.get("image_path"),
            active=d.get("active", True),
        )


class GenerationManager:
    """Manages generation states and history."""

    def __init__(self, state_file: str = "data/ai_trainer/generation_state.json") -> None:
        self._path = Path(state_file)
        self._states: dict[str, GenerationState] = self._load()
        
        # 确保历史记录目录存在
        self._history_root = Path(Config.HISTORY_ROOT)
        self._history_root.mkdir(parents=True, exist_ok=True)
        
        # 为每个评分创建子目录
        for score_dir in Config.SCORE_DIRS.values():
            (self._history_root / score_dir).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, GenerationState]:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                return {uid: GenerationState.from_dict(d) for uid, d in raw.items()}
            except (json.JSONDecodeError, OSError, KeyError):
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        serialised = {uid: state.to_dict() for uid, state in self._states.items()}
        self._path.write_text(
            json.dumps(serialised, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # 历史记录管理
    # ------------------------------------------------------------------
    
    def _get_history_path(self, score: Optional[int] = None) -> Path:
        """Get the path to the history JSON file for a specific score."""
        if score is not None and score in Config.SCORE_DIRS:
            score_dir = Config.SCORE_DIRS[score]
        else:
            score_dir = "unscored"
            (self._history_root / score_dir).mkdir(exist_ok=True)
        
        return self._history_root / score_dir / "history.json"
    
    def _load_history(self, score: Optional[int] = None) -> Dict[str, dict]:
        """Load history records for a specific score."""
        history_path = self._get_history_path(score)
        if history_path.exists():
            try:
                return json.loads(history_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}
    
    def _save_history(self, history: Dict[str, dict], score: Optional[int] = None) -> None:
        """Save history records for a specific score."""
        history_path = self._get_history_path(score)
        history_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    
    def save_to_history(
        self,
        user_id: str,
        prompt: str,
        final_positive: str,
        final_negative: str,
        image_bytes: bytes,
        persona_name: Optional[str] = None,
        score: Optional[int] = None,
    ) -> str:
        """Save a generation to history and return the history ID."""
        
        # 创建历史记录
        timestamp = time.time()
        history = GenerationHistory(
            timestamp=timestamp,
            user_id=user_id,
            prompt=prompt,
            final_positive=final_positive,
            final_negative=final_negative,
            persona_name=persona_name,
            score=score,
        )
        
        # 生成历史记录ID
        history_id = f"{history.datetime_str}_{user_id}"
        
        # 确定存储目录（根据评分）
        if score is not None and score in Config.SCORE_DIRS:
            score_dir = Config.SCORE_DIRS[score]
        else:
            score_dir = "unscored"
            (self._history_root / score_dir).mkdir(exist_ok=True)
        
        # 保存图片
        img_dir = self._history_root / score_dir / history_id
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / "image.png"
        img_path.write_bytes(image_bytes)
        history.image_path = str(img_path)
        
        # 保存提示词到单独的文本文件（方便查看）
        prompt_path = img_dir / "prompt.txt"
        prompt_path.write_text(
            f"原始提示词: {prompt}\n"
            f"最终正面词: {final_positive}\n"
            f"最终负面词: {final_negative}\n"
            f"使用风格: {persona_name or '默认'}\n"
            f"用户评分: {score if score else '未评分'}\n"
            f"生成时间: {datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        
        # 更新历史记录JSON
        history_dict = self._load_history(score)
        history_dict[history_id] = history.to_dict()
        self._save_history(history_dict, score)
        
        # 如果评分已确定，同时更新总历史记录（所有评分汇总）
        if score is not None:
            all_history = self._load_history(None)  # None表示总记录
            all_history[history_id] = history.to_dict()
            self._save_history(all_history, None)
        
        return history_id

    # ------------------------------------------------------------------
    # 状态管理接口
    # ------------------------------------------------------------------

    def get_state(self, user_id: str) -> Optional[GenerationState]:
        state = self._states.get(user_id)
        if state and state.active:
            return state
        return None

    def create_state(self, user_id: str, prompt: str) -> GenerationState:
        """Create (or overwrite) a generation state for the given user."""
        state = GenerationState(user_id=user_id, prompt=prompt)
        self._states[user_id] = state
        self._save()
        return state

    def update_state_with_history(self, user_id: str, history_id: str) -> None:
        """Associate the current state with a history record."""
        state = self._states.get(user_id)
        if state:
            state.history_id = history_id
            self._save()

    def complete_generation(self, user_id: str, score: int) -> None:
        """Mark the generation as complete and update history with score.
        
        Args:
            user_id: 用户ID
            score: 用户评分（1-5）
        """
        state = self._states.get(user_id)
        if state and state.history_id:
            # 从临时目录移动到评分目录
            self._move_to_scored_history(state.history_id, score)
        
        # 标记为不活跃（完成）
        state.active = False
        self._save()
    
    def _move_to_scored_history(self, history_id: str, score: int) -> None:
        """Move an unscored history record to the scored directory."""
        # 加载未评分的历史
        unscored_history = self._load_history(None)
        if history_id not in unscored_history:
            return
        
        # 获取历史记录
        history_dict = unscored_history[history_id]
        
        # 更新评分
        history_dict["score"] = score
        
        # 保存到评分目录
        scored_history = self._load_history(score)
        scored_history[history_id] = history_dict
        self._save_history(scored_history, score)
        
        # 从未评分中删除
        del unscored_history[history_id]
        self._save_history(unscored_history, None)
        
        # 移动图片文件
        old_img_dir = self._history_root / "unscored" / history_id
        new_img_dir = self._history_root / Config.SCORE_DIRS[score] / history_id
        
        if old_img_dir.exists():
            old_img_dir.rename(new_img_dir)
            # 更新图片路径
            history_dict["image_path"] = str(new_img_dir / "image.png")
            
            # 更新评分后的JSON
            scored_history = self._load_history(score)
            scored_history[history_id] = history_dict
            self._save_history(scored_history, score)

    def clear_state(self, user_id: str) -> None:
        """Remove the generation state for a user."""
        self._states.pop(user_id, None)
        self._save()


# Module-level singleton
generation_manager = GenerationManager()