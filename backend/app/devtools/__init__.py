"""运维/测试工具包：对象回收与测试工具共享安全辅助。

仅由 CLI 延迟导入，不在服务启动时加载；不读取 ``.env.prod``。
测试身份 seed 位于 ``tests.acceptance_real.seed``，应用模块不反向依赖 tests。
"""

__all__: list[str] = []
