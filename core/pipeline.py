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
    prompt: str
    final_positive: str
    final_negative: str
    persona_name: Optional[str] = None
    score: Optional[int] = None
    image_path: Optional[str] = None
    model: str = "ponyDiffusionV6XL_v6StartWithThisOne.safetensors"
    
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
    history_id: Optional[str] = None
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

    def __init__(self, state_file: str = Config.PIPELINE_STATE_FILE) -> None:
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
        
        history_id = f"{history.datetime_str}_{user_id}"
        
        if score is not None and score in Config.SCORE_DIRS:
            score_dir = Config.SCORE_DIRS[score]
        else:
            score_dir = "unscored"
            (self._history_root / score_dir).mkdir(exist_ok=True)
        
        img_dir = self._history_root / score_dir / history_id
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / "image.png"
        img_path.write_bytes(image_bytes)
        history.image_path = str(img_path)
        
        prompt_path = img_dir / "prompt.txt"
        prompt_path.write_text(
            f"原始提示词: {prompt}\n"
            f"最终正面词: {final_positive}\n"
            f"最终负面词: {final_negative}\n"
            f"使用角色: {persona_name or '默认'}\n"
            f"用户评分: {score if score is not None else '未评分'}\n"
            f"生成时间: {datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        
        history_dict = self._load_history(score)
        history_dict[history_id] = history.to_dict()
        self._save_history(history_dict, score)
        
        if score is not None:
            all_history = self._load_history(None)
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
        state = GenerationState(user_id=user_id, prompt=prompt)
        self._states[user_id] = state
        self._save()
        return state

    def update_state_with_history(self, user_id: str, history_id: str) -> None:
        state = self._states.get(user_id)
        if state:
            state.history_id = history_id
            self._save()

    def complete_generation(self, user_id: str, score: int) -> None:
        state = self._states.get(user_id)
        if state and state.history_id:
            self._move_to_scored_history(state.history_id, score)
        
        if state:
            state.active = False
            self._save()
    
    def _move_to_scored_history(self, history_id: str, score: int) -> None:
        unscored_history = self._load_history(None)
        if history_id not in unscored_history:
            return
        
        history_dict = unscored_history[history_id]
        history_dict["score"] = score
        
        scored_history = self._load_history(score)
        scored_history[history_id] = history_dict
        self._save_history(scored_history, score)
        
        del unscored_history[history_id]
        self._save_history(unscored_history, None)
        
        old_img_dir = self._history_root / "unscored" / history_id
        new_img_dir = self._history_root / Config.SCORE_DIRS[score] / history_id
        
        if old_img_dir.exists():
            old_img_dir.rename(new_img_dir)
            history_dict["image_path"] = str(new_img_dir / "image.png")
            
            scored_history = self._load_history(score)
            scored_history[history_id] = history_dict
            self._save_history(scored_history, score)

    def clear_state(self, user_id: str) -> None:
        self._states.pop(user_id, None)
        self._save()


generation_manager = GenerationManager()