from pydantic import BaseModel


class WechatMpHtmlStyleItem(BaseModel):
    key: str
    name: str
    group: str
    aliases: list[str]
    suitable_for: list[str]
    is_builtin: bool = True
    is_active: bool = True
    is_default: bool = False
    sort_order: int = 0


class WechatMpHtmlStylePreview(BaseModel):
    key: str
    name: str
    group: str
    html: str


class WechatMpHtmlStyleActiveUpdate(BaseModel):
    is_active: bool

