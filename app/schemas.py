from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class VisitCreate(BaseModel):
    retailer: str = Field(..., min_length=1, description="Retailer/store name, ideally matching the master list")
    market: str = Field(..., min_length=1, description="Market or location visited")
    visit_date: date = Field(..., description="Date of the visit, YYYY-MM-DD")
    feedback: Optional[str] = Field(default="", description="Feedback the retailer gave")
    suggestions: Optional[str] = Field(default="", description="Suggestions or follow-ups")
    submitted_by: Optional[str] = Field(default="Unknown", description="Name of the person logging the visit")


class VisitOut(BaseModel):
    id: int
    retailer: str
    market: str
    visit_date: str
    feedback: str
    suggestions: str
    submitted_by: str
    tl: str
    ss: str
    rds: str
    created_at: str


class RetailerOut(BaseModel):
    code: str
    name: str
    tl: str
    ss: str
    rds: str
    zone: str
    club: str
    status: str


class CoverageRow(BaseModel):
    name: str
    assigned: int
    visited: int
    coverage_pct: float
    total_visits: int


class StatsOut(BaseModel):
    total_visits: int
    unique_retailers_visited: int
    unique_markets: int
    total_retailers_in_master: int
