# 12. 权限控制设计

## 12.1 行级权限（Row Level Security）

根据用户身份自动注入过滤条件。权限配置示例：

```yaml
# configs/permissions.yaml
users:
  u123:
    row_filters:
      region: {operator: "in", value: ["华东", "华南"]}
      department: {operator: "=", value: "sales"}
```

## 12.2 列级权限（Column Level Security）

敏感字段黑名单：

```yaml
sensitive_columns:
  salary: {level: "high", description: "薪资"}
  phone: {level: "high", description: "手机号"}
  id_card: {level: "high", description: "身份证号"}
```

DSL 校验时检测：若 dimensions 包含敏感字段且用户无权限，抛出 `PermissionError`。

## 12.3 数据脱敏

| 字段 | 脱敏规则 |
|------|---------|
| phone | `138****1234` |
| email | `ab***@example.com` |
| id_card | `1101**********1234` |

## 12.4 租户隔离

自动注入 `tenant_id` 过滤条件，确保跨租户数据不可见。
