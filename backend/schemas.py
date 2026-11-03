"""Pydantic contracts shared by the Coordinator (main.py) and the agent service.
The Coordinator re-validates every agent response against these models, so a payload
mismatch between the two services is detected (and counted) instead of silently passed on."""
from typing import Literal, Optional
from pydantic import BaseModel, Field

Mood = Literal["happy", "energetic", "calm", "low"]


class AgentRequest(BaseModel):
    user_id: str
    mood: Optional[Mood] = None
    occasion: str = "Casual"
    season: Optional[str] = None
    mood_log_id: Optional[str] = None
    max_time: Optional[int] = None
    limit: Optional[int] = None


class OutfitItem(BaseModel):
    id: str; name: str; category: str; color: str = ""; style: str = ""; worn_count: int = 0


class Outfit(BaseModel):
    score: float; item_ids: list[str]; items: list[OutfitItem]; reason: str


class StylingOut(BaseModel):
    agent: Literal["styling"] = "styling"
    mood: Optional[Mood]; occasion: str; season: str; wardrobe_size: int
    outfits: list[Outfit]


class MoodStat(BaseModel):
    total: int; completed: int; rate: float


class FocusTask(BaseModel):
    id: str; title: str; priority: str = "medium"; effort: str = "medium"; category: str = "General"
    due_date: Optional[str] = None; score: float; reason: str = ""


class TaskOut(BaseModel):
    agent: Literal["task"] = "task"
    total: int; completed: int; completion_rate: float; streak_days: int
    completed_this_week: int; completed_last_week: int
    week_over_week_change: Optional[float] = None
    per_mood: dict[str, MoodStat]
    focus: list[FocusTask] = []


class Track(BaseModel):
    key: str; title: str; artist: str = ""; emoji: str = ""; description: str = ""; url: str = ""
    moods: list[str] = []; score: float
    preview_url: Optional[str] = None; artwork: Optional[str] = None; apple_url: Optional[str] = None
    embed: Optional[str] = None; external: Optional[str] = None; provider: Optional[str] = None; custom: Optional[bool] = None


class MusicOut(BaseModel):
    agent: Literal["music"] = "music"
    mood_category: Optional[Mood]; playlist: str; tracks: list[Track]


class RecipeCard(BaseModel):
    id: str; name: str; emoji: str = ""; time: Optional[int] = None; tags: list[str] = []
    desc: str = ""; overlap: float; missing: list[str]; score: float


class RecipeOut(BaseModel):
    agent: Literal["recipe"] = "recipe"
    mood: Optional[Mood]; pantry_size: int; recipes: list[RecipeCard]


AGENT_MODELS = {"styling": StylingOut, "task": TaskOut, "music": MusicOut, "recipe": RecipeOut}


class ContextIn(BaseModel):
    mood: str = Field(min_length=1, max_length=40)
    occasion: str = Field("Casual", min_length=1, max_length=40)
    season: Optional[str] = None
    max_time: Optional[int] = Field(None, ge=1, le=600)


class FeedbackIn2(BaseModel):
    domain: Literal["styling", "music", "recipe"]
    accepted: bool
    mood_log_id: Optional[str] = None
    item_ids: Optional[list[str]] = None     # styling
    track_key: Optional[str] = None          # music
    recipe_id: Optional[str] = None          # recipe
