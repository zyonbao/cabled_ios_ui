"""Stub of traitlets.config. `Config` is only built inside
pymobiledevice3.utils.start_ipython_shell (never run by the GUI). The lenient
attribute behavior supports `config.Section.option = value` chains."""


class Config:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        child = Config()
        object.__setattr__(self, name, child)
        return child
