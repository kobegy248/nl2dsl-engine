"""反馈数据模型与 issue_type 枚举。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 统一的反馈 issue_type 枚举（与 api_factory.FEEDBACK_ISSUE_TYPES 保持一致）
FEEDBACK_ISSUE_TYPES = (
    "intent", "metric", "dimension", "filter", "time", "join",
    "ranking", "proportion", "permission", "result", "other",
)

# 候选审核状态
REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_APPROVED = "approved"
REVIEW_STATUS_REJECTED = "rejected"


@dataclass
class FeedbackRecord:
    """一条用户反馈（对应 nl2dsl_feedback 表的一行）。"""

    feedback_id: str
    query_id: str
    user_id: str
    tenant_id: str
    is_correct: bool
    issue_type: str | None = None
    corrected_dsl: dict | None = None
    comment: str = ""
    dedup_hash: str = ""
    review_status: str = REVIEW_STATUS_PENDING
    created_at: str = ""

    def to_dict(self, *, include_dsl: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "feedback_id": self.feedback_id,
            "query_id": self.query_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "is_correct": self.is_correct,
            "issue_type": self.issue_type,
            "comment": self.comment,
            "dedup_hash": self.dedup_hash,
            "review_status": self.review_status,
            "created_at": self.created_at,
        }
        if include_dsl:
            data["corrected_dsl"] = self.corrected_dsl
        return data
