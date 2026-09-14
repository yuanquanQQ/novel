# 懒加载 config 代理。在 set_novel() 之后，所有 config.xxx 自动解析。

from engine.settings import get_config


class _ConfigProxy:
    def __getattr__(self, name):
        return getattr(get_config(), name)


config = _ConfigProxy()
