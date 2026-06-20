"""数据库 FeedbackStore —— 与 Audit 共用同一 SQLAlchemy Engine。

Phase 4：

- 写入前校验 Audit query_id 存在、user_id / tenant_id 匹配。
- corrected_dsl 通过 DSL Schema 校验。
- 稳定 SHA-256 去重，重复提交返回原 feedback_id。
- 不在反馈表复制 SQL 和 Trace（按需联合 Audit 查询）。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import Engine, text

from nl2dsl.audit.logger import AuditLogger
from nl2dsl.exceptions import NotFoundError, ValidationError
from nl2dsl.feedback.models import (
    FEEDBACK_ISSUE_TYPES,
    REVIEW_STATUS_PENDING,
    FeedbackRecord,
)
from nl2dsl.utils.logger import get_logger

logger = get_logger("feedback.store")


def compute_dedup_hash(
    *,
    query_id: str,
    user_id: str,
    tenant_id: str,
    is_correct: bool,
    issue_type: str | None,
    corrected_dsl: dict | None,
    comment: str,
) -> str:
    """对反馈关键字段计算稳定 SHA-256。

    corrected_dsl 以排序后的 JSON 参与，保证键顺序不影响哈希。
    """
    payload = json.dumps(
        {
            "query_id": query_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "is_correct": bool(is_correct),
            "issue_type": issue_type or "",
            "corrected_dsl": corrected_dsl or {},
            "comment": comment or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FeedbackStore:
    """正式运行的反馈存储，与 Audit 共用 Engine。"""

    def __init__(self, engine: Engine, audit_logger: AuditLogger | None = None):
        self._engine = engine
        self._audit = audit_logger or AuditLogger(engine)
        self._ensure_table()

    def _ensure_table(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS nl2dsl_feedback (
            feedback_id TEXT PRIMARY KEY,
            query_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            is_correct INTEGER NOT NULL,
            issue_type TEXT,
            corrected_dsl TEXT,
            comment TEXT,
            dedup_hash TEXT NOT NULL UNIQUE,
            review_status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        with self._engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_corrected_dsl(corrected_dsl: dict | None) -> None:
        if not corrected_dsl:
            return
        from nl2dsl.dsl.models import DSL
        try:
            DSL.model_validate(corrected_dsl)
        except Exception as exc:
            raise ValidationError(f"corrected_dsl 不合法：{exc}")

    @staticmethod
    def _require_non_blank_tenant(tenant_id: str) -> str:
        """租户隔离的防御性校验：tenant_id 必须非空白。

        不依赖 Pydantic；Store 层直接调用时同样生效。空值直接拒绝，避免
        “请求 tenant_id 缺失时跳过跨租户比较”的绕过。
        """
        if tenant_id is None or not str(tenant_id).strip():
            raise ValidationError("tenant_id 不能为空")
        return str(tenant_id).strip()

    def _validate_against_audit(
        self, *, query_id: str, user_id: str, tenant_id: str
    ) -> dict:
        record = self._audit.get_query(query_id)
        if record is None:
            raise NotFoundError(f"审计记录不存在：query_id={query_id}")
        if record.get("user_id") != user_id:
            raise ValidationError("user_id 与审计记录不一致")
        # 严格租户校验：请求 tenant_id 必须非空（防御性，不依赖 API 层）。
        req_tenant = self._require_non_blank_tenant(tenant_id)
        # 审计记录有 tenant_id 时，请求必须严格相等；缺失/为空/不一致一律拒绝。
        audit_tenant = (record.get("tenant_id") or "").strip()
        if audit_tenant:
            if audit_tenant != req_tenant:
                raise ValidationError("tenant_id 与审计记录不一致")
        else:
            # 审计记录本身缺少 tenant_id：无法证明同租户，拒绝以避免跨租户写入。
            raise ValidationError("审计记录缺少 tenant_id，无法校验租户归属")
        return record

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def submit(
        self,
        *,
        query_id: str,
        user_id: str,
        tenant_id: str,
        is_correct: bool = True,
        issue_type: str | None = None,
        corrected_dsl: dict | None = None,
        comment: str = "",
    ) -> tuple[str, bool]:
        """提交反馈，返回 (feedback_id, deduplicated)。

        - 校验失败抛 ``NotFoundError`` / ``ValidationError``。
        - 重复提交返回原 feedback_id，``deduplicated=True``。
        """
        if issue_type and issue_type not in FEEDBACK_ISSUE_TYPES:
            raise ValidationError(f"非法 issue_type：{issue_type}")

        # 统一规范化 tenant_id（非空校验 + 去空白），保证后续校验与去重哈希一致。
        tenant_id = self._require_non_blank_tenant(tenant_id)

        # 至少提供一项有效反馈
        has_feedback = (
            is_correct is False
            or bool(corrected_dsl)
            or bool((comment or "").strip())
        )
        if not has_feedback:
            raise ValidationError("至少需要 is_correct=false / corrected_dsl / 非空 comment 之一")

        self._validate_against_audit(query_id=query_id, user_id=user_id, tenant_id=tenant_id)
        self._validate_corrected_dsl(corrected_dsl)

        dedup_hash = compute_dedup_hash(
            query_id=query_id, user_id=user_id, tenant_id=tenant_id,
            is_correct=is_correct, issue_type=issue_type,
            corrected_dsl=corrected_dsl, comment=comment,
        )

        # 原子去重：直接 INSERT，依赖 dedup_hash 的 UNIQUE 约束捕获并发竞争。
        # 命中约束时回查已有 feedback_id 并返回（deduplicated=True），避免
        # “先 SELECT 后 INSERT”的竞态在并发下抛 500。
        feedback_id = f"fb-{uuid.uuid4().hex[:16]}"
        from sqlalchemy.exc import IntegrityError

        with self._engine.connect() as conn:
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO nl2dsl_feedback
                            (feedback_id, query_id, user_id, tenant_id, is_correct,
                             issue_type, corrected_dsl, comment, dedup_hash, review_status)
                        VALUES
                            (:feedback_id, :query_id, :user_id, :tenant_id, :is_correct,
                             :issue_type, :corrected_dsl, :comment, :dedup_hash, :review_status)
                        """
                    ),
                    {
                        "feedback_id": feedback_id,
                        "query_id": query_id,
                        "user_id": user_id,
                        "tenant_id": tenant_id,
                        "is_correct": 1 if is_correct else 0,
                        "issue_type": issue_type,
                        "corrected_dsl": json.dumps(corrected_dsl, ensure_ascii=False) if corrected_dsl else None,
                        "comment": comment,
                        "dedup_hash": dedup_hash,
                        "review_status": REVIEW_STATUS_PENDING,
                    },
                )
                conn.commit()
            except IntegrityError:
                conn.rollback()
                existing = conn.execute(
                    text("SELECT feedback_id FROM nl2dsl_feedback WHERE dedup_hash = :h"),
                    {"h": dedup_hash},
                ).first()
                if existing is not None:
                    logger.info("反馈去重命中（约束竞争），返回原 feedback_id=%s", existing[0])
                    return existing[0], True
                raise ValidationError("反馈写入失败：去重约束冲突但未找到既有记录")
        logger.info("反馈已写入 feedback_id=%s query_id=%s", feedback_id, query_id)
        return feedback_id, False

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def get(self, feedback_id: str, *, tenant_id: str | None = None) -> FeedbackRecord | None:
        """按 feedback_id 读取一条反馈。

        当传入 ``tenant_id`` 时，在 SQL 层直接加上租户过滤：记录不存在或属于
        其他租户都返回 ``None``。这是反馈详情接口租户隔离的下沉点，避免 API
        层取出跨租户数据后再判断。
        """
        with self._engine.connect() as conn:
            if tenant_id:
                row = conn.execute(
                    text(
                        "SELECT * FROM nl2dsl_feedback "
                        "WHERE feedback_id = :fid AND tenant_id = :tenant_id"
                    ),
                    {"fid": feedback_id, "tenant_id": tenant_id},
                ).first()
            else:
                row = conn.execute(
                    text("SELECT * FROM nl2dsl_feedback WHERE feedback_id = :fid"),
                    {"fid": feedback_id},
                ).first()
        if row is None:
            return None
        return self._row_to_record(dict(row._mapping))

    def list(
        self,
        *,
        user_id: str | None = None,
        tenant_id: str | None = None,
        query_id: str | None = None,
        review_status: str | None = None,
        is_correct: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[FeedbackRecord], int]:
        clauses: list[str] = []
        params: dict = {}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if tenant_id is not None:
            clauses.append("tenant_id = :tenant_id")
            params["tenant_id"] = tenant_id
        if query_id is not None:
            clauses.append("query_id = :query_id")
            params["query_id"] = query_id
        if review_status is not None:
            clauses.append("review_status = :review_status")
            params["review_status"] = review_status
        if is_correct is not None:
            clauses.append("is_correct = :is_correct")
            params["is_correct"] = 1 if is_correct else 0

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        list_sql = (
            f"SELECT * FROM nl2dsl_feedback {where} "
            f"ORDER BY created_at DESC, feedback_id DESC LIMIT :limit OFFSET :offset"
        )
        count_sql = f"SELECT COUNT(*) FROM nl2dsl_feedback {where}"
        with self._engine.connect() as conn:
            lp = {**params, "limit": limit, "offset": offset}
            rows = [dict(r._mapping) for r in conn.execute(text(list_sql), lp)]
            total = conn.execute(text(count_sql), params).scalar() or 0
        return [self._row_to_record(r) for r in rows], int(total)

    def list_for_export(
        self, *, review_status: str | None = REVIEW_STATUS_PENDING
    ) -> list[FeedbackRecord]:
        """导出用：返回所有（默认 pending）反馈记录。"""
        records, _ = self.list(review_status=review_status, limit=100000, offset=0)
        return records

    @staticmethod
    def _row_to_record(row: dict) -> FeedbackRecord:
        corrected = row.get("corrected_dsl")
        return FeedbackRecord(
            feedback_id=row["feedback_id"],
            query_id=row["query_id"],
            user_id=row["user_id"],
            tenant_id=row.get("tenant_id") or "",
            is_correct=bool(row.get("is_correct")),
            issue_type=row.get("issue_type"),
            corrected_dsl=json.loads(corrected) if corrected else None,
            comment=row.get("comment") or "",
            dedup_hash=row.get("dedup_hash") or "",
            review_status=row.get("review_status") or REVIEW_STATUS_PENDING,
            created_at=str(row.get("created_at") or ""),
        )
