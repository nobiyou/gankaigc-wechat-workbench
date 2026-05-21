from pydantic import BaseModel


class TrendItem(BaseModel):
    slug: str
    title: str
    source: str
    heat_score: int
    status: str


class TrendCreate(TrendItem):
    pass


class TrendUpdate(BaseModel):
    title: str
    heat_score: int
    status: str


class TrendImportRequest(BaseModel):
    raw_text: str


class TrendImportResult(BaseModel):
    line_number: int
    raw_line: str
    status: str
    error: str | None = None
    trend: TrendItem | None = None


class TrendImportResponse(BaseModel):
    run_id: int | None = None
    requested_count: int
    created_count: int
    skipped_count: int = 0
    failed_count: int
    results: list[TrendImportResult]
