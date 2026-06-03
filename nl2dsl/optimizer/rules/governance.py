"""Governance rules: G001 (Sensitive Field Access), G002 (Metric Not Authorized)."""

from nl2dsl.optimizer.base import BaseRule, RuleResult
from nl2dsl.optimizer.metadata import RuleMetadata
from nl2dsl.optimizer.registry import RuleRegistry


@RuleRegistry.register
class G001_SensitiveFieldAccess(BaseRule):
    """Check if the query accesses sensitive fields without masking."""

    metadata = RuleMetadata(
        error_code="G001",
        category="Governance",
        description="Query accesses sensitive fields without proper authorization or masking",
        priority=4,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        permission_config = context.permission_config or {}
        sensitive_fields = permission_config.get("sensitive_fields", {})
        masking_rules = permission_config.get("masking_rules", {})

        if not sensitive_fields:
            return RuleResult.no_issue("G001", "Governance")

        # Collect all fields referenced in the DSL
        referenced_fields = set()

        # From metrics
        for m in (dsl.get("metrics") or []):
            alias = m.get("alias", "")
            if alias:
                field = context.semantic_config.get_metric_field(alias)
                if field:
                    referenced_fields.add(field)
            referenced_fields.add(m.get("field", ""))

        # From dimensions
        for d in (dsl.get("dimensions") or []):
            col = context.semantic_config.get_dimension_column(d)
            referenced_fields.add(col or d)

        # From filters
        for f in (dsl.get("filters") or []):
            if isinstance(f, dict):
                referenced_fields.add(f.get("field", ""))

        # Check sensitive fields
        for field in referenced_fields:
            if not field:
                continue
            if field in sensitive_fields:
                # Check if masking is configured for this field
                if field not in masking_rules:
                    user_role = context.user_role or "anonymous"
                    return RuleResult.from_metadata(
                        self.metadata,
                        description=f"Sensitive field '{field}' accessed by role '{user_role}' without masking rule",
                        before={"field": field, "role": user_role},
                        location=f"sensitive_field:{field}",
                    )

        return RuleResult.no_issue("G001", "Governance")


@RuleRegistry.register
class G002_MetricNotAuthorized(BaseRule):
    """Check if the user's role has access to all requested metrics."""

    metadata = RuleMetadata(
        error_code="G002",
        category="Governance",
        description="User role does not have permission to access requested metrics",
        priority=4,
        severity="Reject",
        confidence="high",
        is_fatal=True,
    )

    def check(self, dsl: dict, context) -> RuleResult:
        permission_config = context.permission_config or {}
        metric_permissions = permission_config.get("metric_permissions", {})

        if not metric_permissions:
            return RuleResult.no_issue("G002", "Governance")

        user_role = context.user_role or "anonymous"

        for m in (dsl.get("metrics") or []):
            alias = m.get("alias", "")
            if not alias:
                continue

            # Check if this metric has role restrictions
            allowed_roles = metric_permissions.get(alias)
            if allowed_roles is not None and user_role not in allowed_roles:
                return RuleResult.from_metadata(
                    self.metadata,
                    description=f"Role '{user_role}' is not authorized to access metric '{alias}'"
                                + f" (allowed: {allowed_roles})",
                    before={"metric": alias, "role": user_role},
                    location=f"metrics[alias={alias}]",
                )

        return RuleResult.no_issue("G002", "Governance")
