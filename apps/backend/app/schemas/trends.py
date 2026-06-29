from pydantic import BaseModel


class TrendItem(BaseModel):
    slug: str
    title: str
    source: str
    heat_score: int
    status: str
    link: str = ""
    summary: str = ""
    published_at: str | None = None
    fetched_at: str | None = None


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


class TrendFetchSourceResult(BaseModel):
    source_url: str
    source_label: str
    status: str
    fetched_count: int
    created_count: int
    skipped_count: int
    failed_count: int
    error: str | None = None


class TrendFetchResponse(BaseModel):
    run_id: int | None = None
    requested_source_count: int
    processed_source_count: int
    created_count: int
    skipped_count: int
    failed_count: int
    results: list[TrendFetchSourceResult]
