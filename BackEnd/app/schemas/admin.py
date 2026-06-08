from pydantic import BaseModel
from typing import Optional


class DocumentUploadResponse(BaseModel):
    success: bool
    source: str
    file_name: str
    chunks: int
    message: str


class DocumentListItem(BaseModel):
    source: str
    file_name: Optional[str] = None
    chunks: int


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    total: int


class DocumentDeleteResponse(BaseModel):
    success: bool
    source: str
    message: str
