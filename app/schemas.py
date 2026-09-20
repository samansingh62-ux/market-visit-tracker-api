from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class VisitCreate(BaseModel):
    retailer: str = Field(..., min_length=1)
    market: str = Field(..., min_length=1)
    visit_date: date
    feedback: Optional[str] = ""
    suggestions: Optional[str] = ""
    submitted_by: Optional[str] = "Unknown"
    submitted_role: Optional[str] = "Field"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    gps_accuracy: Optional[float] = None


class VisitOut(BaseModel):
    id: int
    retailer: str
    market: str
    visit_date: str
    feedback: str
    suggestions: str
    submitted_by: str
    submitted_role: str
    tl: str
    ss: str
    rds: str
    created_at: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    gps_accuracy: Optional[float] = None
    photo_count: int = 0


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


# IMPORTANT:
# UserOut must be defined BEFORE LoginOut.
class UserOut(BaseModel):
    id: int
    name: str
    role: str
    tl: Optional[str] = None
    ss: Optional[str] = None
    rds: Optional[str] = None
    active: bool


class AdminUserOut(BaseModel):
    id: int
    name: str
    role: str
    tl: Optional[str] = None
    ss: Optional[str] = None
    rds: Optional[str] = None
    username: str
    active: bool
    assigned_retailers: int


class PasswordResetOut(BaseModel):
    id: int
    name: str
    role: str
    username: str
    temporary_password: str


class UserStatusOut(BaseModel):
    id: int
    name: str
    role: str
    username: str
    active: bool


class RetailerHealthOut(BaseModel):
    code: str
    name: str
    tl: str
    ss: str
    rds: str
    zone: str
    club: str
    status: str
    visit_count: int
    last_visit: Optional[str] = None
    days_since_visit: Optional[int] = None
    priority: str


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class PinLoginRequest(BaseModel):
    name: str = Field(..., min_length=1)
    role: str = Field(..., pattern="^(TL|SS)$")
    pin: str = Field(..., min_length=4, max_length=4)


class LoginOut(BaseModel):
    access_token: str
    token_type: str
    user: UserOut


class PhotoOut(BaseModel):
    id: int
    visit_id: int
    filename: str
    mime_type: str
    size_bytes: int
    created_at: str
    url: str
