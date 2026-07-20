from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Company:
    cik: int
    ticker: str
    name: str


CURATED: list[Company] = [
    Company(320193, "AAPL", "Apple Inc."),
    Company(789019, "MSFT", "Microsoft Corporation"),
    Company(1018724, "AMZN", "Amazon.com, Inc."),
    Company(1652044, "GOOGL", "Alphabet Inc."),
    Company(1326801, "META", "Meta Platforms, Inc."),
    Company(1045810, "NVDA", "NVIDIA Corporation"),
    Company(1318605, "TSLA", "Tesla, Inc."),
    Company(19617, "JPM", "JPMorgan Chase & Co."),
    Company(200406, "JNJ", "Johnson & Johnson"),
    Company(104169, "WMT", "Walmart Inc."),
]


def by_ticker(ticker: str) -> Company:
    for company in CURATED:
        if company.ticker == ticker.upper():
            return company
    raise KeyError(f"unknown ticker: {ticker}")
