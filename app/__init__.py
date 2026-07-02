"""astrbot_plugin_animewifex v3.x 应用层包。

模块化分层：
- ``commands`` ：双轨命令注册表与各命令处理实现
- ``services`` ：业务服务层（抽老婆、所有权、NTR、经济、PK 等）
- ``storage`` ：JSON 原子读写、群锁、路径常量与各实体 Store
- ``models``  ：dataclass 形式的数据模型与枚举
- ``api``     ：AstrMessageEvent / 消息链构建辅助
- ``utils``   ：时间、图片、随机、格式化等纯函数工具
"""

__all__ = [
    "commands",
    "services",
    "storage",
    "models",
    "api",
    "utils",
]
