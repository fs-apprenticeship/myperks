# backend/api/schemas/admin.py

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

DEPARTMENT_VALUES = Literal[
    "engineering", "sales", "marketing", "hr", "finance", "operations", "other"
]
ROLE_VALUES = Literal["employee", "hr_admin"]


class ApproveRejectBody(BaseModel):
    status: Literal["approved", "rejected"]
    rejection_reason: str | None = None


class BalanceSnapshot(BaseModel):
    leave_type: str
    total_days: float
    used_days: float
    remaining_days: float


class ApproveRejectResponse(BaseModel):
    request_id: int
    employee_name: str
    employee_email: str
    request_type: str
    new_status: str
    rejection_reason: str | None
    updated_balances: list[BalanceSnapshot]


class RequestHistorySnapshot(BaseModel):
    id: int
    type: str
    status: str
    created_at: datetime
    body: str | None


class EmployeeListItem(BaseModel):
    id: int
    name: str
    email: str
    department: str
    role: str
    joined_date: date
    linked: bool  # True when clerk_user_id is set


class PaginatedEmployees(BaseModel):
    items: list[EmployeeListItem]
    total: int
    page: int
    size: int
    pages: int


class EmployeeDetail(BaseModel):
    id: int
    name: str
    email: str
    department: str
    role: str
    joined_date: date
    benefits_year_reset: date
    linked: bool
    balances: list[BalanceSnapshot]  # reuses existing schema
    request_history: list[RequestHistorySnapshot]


class PreCreateEmployeeBody(BaseModel):
    name: str
    email: str
    department: DEPARTMENT_VALUES
    joined_date: date
    benefits_year_reset: date


class PreCreateEmployeeResponse(BaseModel):
    id: int
    name: str
    email: str
    department: str
    role: str
    joined_date: date
    benefits_year_reset: date
    linked: bool  # always False on pre-create


class PatchEmployeeBody(BaseModel):
    department: DEPARTMENT_VALUES | None = None
    role: ROLE_VALUES | None = None


class PatchEmployeeResponse(BaseModel):
    id: int
    name: str
    email: str
    department: str
    role: str
    joined_date: date
    benefits_year_reset: date
    linked: bool


class RequestListItem(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    type: str
    status: str
    created_at: datetime
    body: str | None


class PaginatedRequests(BaseModel):
    items: list[RequestListItem]
    total: int
    page: int
    size: int
    pages: int


# ── Document extraction schemas ──────────────────────────────────────────────


class ExtractionData(BaseModel):
    vacation_days: float | None = None
    sick_days: float | None = None
    pto_days: float | None = None
    # null = uncapped/unspecified carryover, 0 = forfeited, N = capped at N (T46)
    carryover_cap_days: float | None = None
    # "monthly" | "none" | null (not stated -> company default applies) (T46)
    proration_method: str | None = None
    notes: str = ""


class DocumentExtractionResponse(BaseModel):
    id: int
    document_id: int
    status: str
    extracted_data: ExtractionData | None = None
    approved_data: ExtractionData | None = None
    reviewed_at: datetime | None = None
    error_message: str | None = None


class ApproveExtractionBody(BaseModel):
    # 365 is a sanity bound (annual leave can't exceed a year), not a tunable —
    # mirrors the same bound rag/extract.py applies to the raw LLM output.
    vacation_days: float | None = Field(None, ge=0, le=365)
    sick_days: float | None = Field(None, ge=0, le=365)
    pto_days: float | None = Field(None, ge=0, le=365)
    # Carryover/proration rules persisted into approved_data so
    # services.vacation.seed_employee_vacation_balances and the rollover job
    # can read them (T46). null carryover means uncapped/unspecified (company
    # default of 5 vacation days applies).
    carryover_cap_days: float | None = Field(None, ge=0, le=365)
    proration_method: Literal["monthly", "none"] | None = None
    notes: str = ""
    year: int = Field(..., ge=2000, le=2100)

    @model_validator(mode="after")
    def _require_at_least_one_leave_field(self) -> "ApproveExtractionBody":
        if (
            self.vacation_days is None
            and self.sick_days is None
            and self.pto_days is None
        ):
            raise ValueError(
                "At least one of vacation_days, sick_days, or pto_days must be set."
            )
        return self


class ApproveExtractionResponse(BaseModel):
    extraction_id: int
    document_id: int
    department: str
    year: int
    employees_updated: int
    warning: str | None = None


class DepartmentPolicyItem(BaseModel):
    department: str
    document_id: int
    vacation_days: float | None
    sick_days: float | None
    pto_days: float | None
    notes: str
    approved_at: datetime


class DepartmentPoliciesResponse(BaseModel):
    policies: list[DepartmentPolicyItem]


class DepartmentBalanceItem(BaseModel):
    department: str
    employee_count: int
    vacation_days: float | None
    sick_days: float | None
    pto_days: float | None


class DepartmentBalancesResponse(BaseModel):
    year: int
    departments: list[DepartmentBalanceItem]
