"""
myPerks — ORM Models
backend/db/models.py
"""

from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

extraction_status_enum = Enum(
    "pending",
    "extracting",
    "extracted",
    "approved",
    "failed",
    name="extraction_status",
)


class Base(DeclarativeBase):
    pass


# Shared Postgres ENUM used by BOTH employees.department and documents.department.
# Defined once as a single object so SQLAlchemy emits one CREATE TYPE and both
# columns reference the same type. The Alembic migration (T21) owns creation in
# the live DB; this object is the source of truth for the ORM and tests.
department_enum = Enum(
    "engineering",
    "sales",
    "marketing",
    "hr",
    "finance",
    "operations",
    "other",
    # Document-only scope value (T39): a document tagged "all" is company-wide
    # and reaches every department in RAG retrieval. Never a valid value for
    # employees.department — that is gated at the app layer (the schema Literals
    # in api/schemas/admin.py and the DEPARTMENTS set in routers/employees.py).
    "all",
    name="department",
)


class Employee(Base):
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Nullable: HR can pre-create an employee row (email + department) before that
    # person ever signs in. On first Clerk login we link the row by email and set
    # this (T25 pre-create / T27 link-by-email). Stays unique — Postgres treats
    # NULLs as distinct, so multiple unlinked rows coexist.
    clerk_user_id = Column(String(128), unique=True, nullable=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        Enum("employee", "hr_admin", name="employee_role"),
        nullable=False,
        server_default="employee",
    )
    department: Mapped[str] = mapped_column(department_enum, nullable=False)
    joined_date: Mapped[date] = mapped_column(Date, nullable=False)
    benefits_year_reset: Mapped[date] = mapped_column(Date, nullable=False)

    vacation_balances = relationship(
        "VacationBalance", back_populates="employee", cascade="all, delete-orphan"
    )
    request_histories = relationship(
        "RequestHistory", back_populates="employee", cascade="all, delete-orphan"
    )
    documents = relationship(
        "Document", back_populates="uploader", cascade="all, delete-orphan"
    )
    conversations = relationship(
        "Conversation", back_populates="employee", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "Notification", back_populates="recipient", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Employee id={self.id} name={self.name!r}>"


class VacationBalance(Base):
    __tablename__ = "vacation_balances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(
        Integer, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    leave_type: Mapped[str] = mapped_column(
        Enum("vacation", "sick", "pto", name="leave_type"),
        nullable=False,
    )
    total_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    used_days: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    year = Column(Integer, nullable=False)

    employee = relationship("Employee", back_populates="vacation_balances")

    # One row per employee, per year, per leave type
    __table_args__ = (
        Index(
            "ix_vacation_balance_employee_year_type",
            "employee_id",
            "year",
            "leave_type",
            unique=True,
        ),
    )

    @property
    def remaining_days(self) -> float:
        return self.total_days - self.used_days

    def __repr__(self) -> str:
        return (
            f"<VacationBalance employee_id={self.employee_id} "
            f"year={self.year} type={self.leave_type} remaining={self.remaining_days}>"
        )


class RequestHistory(Base):
    __tablename__ = "request_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type = Column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", "cancelled", name="request_status"),
        nullable=False,
        default="pending",
    )
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    body = Column(Text, nullable=True)

    employee = relationship("Employee", back_populates="request_histories")

    def __repr__(self) -> str:
        return (
            f"<RequestHistory id={self.id} type={self.type!r} status={self.status!r}>"
        )


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(512), nullable=False)
    content_sha256 = Column(String(64), nullable=True, unique=True, index=True)
    uploaded_by = Column(
        Integer,
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    uploaded_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    # A document belongs to one department, or to the company-wide "all" tier
    # (T39). Drives department-scoped RAG retrieval (T28): an employee sees
    # their own department plus "all". Reuses the shared enum.
    department: Mapped[str] = mapped_column(department_enum, nullable=False)

    uploader = relationship("Employee", back_populates="documents")
    chunks = relationship(
        "DocumentChunk", back_populates="document", cascade="all, delete-orphan"
    )
    extraction = relationship(
        "DocumentExtraction",
        back_populates="document",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} filename={self.filename!r}>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_document_chunk_doc_idx", "document_id", "chunk_index", unique=True),
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk id={self.id} document_id={self.document_id} "
            f"chunk_index={self.chunk_index}>"
        )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(
        String(255), nullable=True
    )  # optional summary/title of the conversation
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    employee = relationship("Employee", back_populates="conversations")
    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} employee_id={self.employee_id}>"


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        Enum("user", "assistant", name="message_role"),
        nullable=False,
    )
    content = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} conversation_id={self.conversation_id} "
            f"role={self.role!r}>"
        )


class DocumentExtraction(Base):
    """Stores LLM-extracted HR policy data from an uploaded document.

    One-to-one with Document. HR reviews the extracted fields, edits if needed,
    then approves — which writes approved_data to VacationBalance for the dept.
    """

    __tablename__ = "document_extractions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        extraction_status_enum,
        nullable=False,
        default="pending",
    )
    # JSON: {vacation_days, sick_days, pto_days, notes}
    extracted_data = Column(Text, nullable=True)
    # JSON written on HR approval — may differ from extracted_data after edits
    approved_data = Column(Text, nullable=True)
    reviewed_by = Column(
        Integer,
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    document = relationship("Document", back_populates="extraction")
    reviewer = relationship("Employee", foreign_keys=[reviewed_by])

    def __repr__(self) -> str:
        return (
            f"<DocumentExtraction id={self.id} document_id={self.document_id} "
            f"status={self.status!r}>"
        )


class Notification(Base):
    """An in-app notification for one recipient about one request event."""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recipient_id = Column(
        Integer,
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
    )
    related_request_id = Column(
        Integer,
        ForeignKey("request_histories.id", ondelete="CASCADE"),
        nullable=False,
    )
    type: Mapped[str] = mapped_column(
        Enum("request_submitted", "request_status_changed", name="notification_type"),
        nullable=False,
    )
    message = Column(Text, nullable=False)
    payload = Column(Text, nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    recipient = relationship("Employee", back_populates="notifications")

    # Primary access pattern, a recipient's notifications, newest first.
    __table_args__ = (
        Index("ix_notifications_recipient_created", "recipient_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} recipient_id={self.recipient_id} "
            f"type={self.type!r}>"
        )
