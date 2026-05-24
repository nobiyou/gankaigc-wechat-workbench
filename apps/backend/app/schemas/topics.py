from pydantic import BaseModel


class TopicItem(BaseModel):
    slug: str
    trend_slug: str | None = None
    source_type: str = "trend"
    source_ref_slug: str
    title: str
    angle: str
    status: str


class TopicCreateFromTrend(BaseModel):
    slug: str
    title: str
    angle: str


class TopicCreate(BaseModel):
    slug: str
    title: str
    angle: str


class TopicUpdate(BaseModel):
    title: str
    angle: str
    status: str
