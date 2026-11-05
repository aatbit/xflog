from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    followers: StrictBool = True
    subscriptions: StrictBool = False
    notifications: StrictBool = False
    follow_actions: StrictBool = False
    profile_names: StrictBool = False
    interactions: dict[str, StrictBool] | None = None


class StartRequest(BaseModel):
    accepted_costs: StrictBool


class AudiencePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: dict[str, StrictBool]


class FollowTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: StrictStr = Field(min_length=1, max_length=200)
    demo: StrictBool = False


class FollowChange(FollowTarget):
    following: StrictBool


class ThreadRequest(FollowTarget):
    sequence: StrictInt = Field(gt=0, le=9223372036854775807)
    action: Literal["open", "cached", "more", "refresh"] = "open"
    checked_at: StrictStr | None = None
    offset: StrictInt = Field(default=0, ge=0, le=1000000)
    accepted_costs: StrictBool = False
