from pydantic import BaseModel


class TrackedArticleItem(BaseModel):
    slug: str
    source_name: str
    title: str
    url: str
    author: str
    summary: str
    structure_notes: str
    tags: list[str]


class TrackedArticleCreate(TrackedArticleItem):
    pass
