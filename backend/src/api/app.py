from __future__ import annotations

import json
from functools import lru_cache
from typing import Iterator

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from pipeline import db
from pipeline.embed import Embedder

from .answer import AnswerEvent, answer_stream
from .generate import AnthropicGenerator, Generator

app = FastAPI(title="EDGAR Answers", version="0.1.0")


class Filters(BaseModel):
    ticker: str | None = None
    form_type: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    filters: Filters = Field(default_factory=Filters)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value.strip()


@lru_cache(maxsize=1)
def _embedder() -> Embedder:
    """One process-wide embedder: loading the ONNX weights per request would
    dominate latency."""
    return Embedder()


def get_embedder() -> Embedder:
    return _embedder()


def get_generator() -> Generator:
    return AnthropicGenerator()


def sse(event: AnswerEvent) -> str:
    payload = json.dumps(event.data, separators=(",", ":"))
    return f"event: {event.name}\ndata: {payload}\n\n"


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask")
def ask(
    request: AskRequest,
    embedder: Embedder = Depends(get_embedder),
    generator: Generator = Depends(get_generator),
) -> StreamingResponse:
    def events() -> Iterator[str]:
        # A connection per request; pooling is a Phase 5 concern.
        with db.connect() as conn:
            for event in answer_stream(
                conn,
                embedder,
                generator,
                request.question,
                ticker=request.filters.ticker,
                form_type=request.filters.form_type,
            ):
                yield sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
