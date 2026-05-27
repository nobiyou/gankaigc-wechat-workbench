from pydantic import BaseModel


class ToneProfileItem(BaseModel):
    id: int
    is_active: bool
    sort_order: int
    name: str
    opening_style: str
    paragraph_rhythm: str
    closing_style: str
    forbidden_phrases: list[str]
    value_constraints: str
    target_word_count: int
    default_polish_instruction: str = ""


class ToneProfileUpsert(BaseModel):
    name: str
    opening_style: str
    paragraph_rhythm: str
    closing_style: str
    forbidden_phrases: list[str]
    value_constraints: str
    target_word_count: int
    default_polish_instruction: str = ""


class ToneProfileReorder(BaseModel):
    profile_ids: list[int]
