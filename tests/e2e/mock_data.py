"""兼容 shim：样例数据生成已迁移到正式包 ``nl2dsl.testing.sample_data``。

保留此模块以兼容现有测试导入（``from tests.e2e.mock_data import ...``）。
正式 CLI 不应再导入 ``tests.*``，请改用 ``nl2dsl.testing.sample_data``。
"""

from nl2dsl.testing.sample_data import *  # noqa: F401,F403
from nl2dsl.testing.sample_data import create_mock_database  # noqa: F401
