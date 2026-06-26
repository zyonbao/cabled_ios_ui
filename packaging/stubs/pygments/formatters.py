"""Stub of pygments.formatters. Any formatter name (e.g. Terminal256Formatter)
resolves to a no-op class — only referenced from never-run shell code."""


def __getattr__(name):
    return type(name, (), {"__init__": lambda self, *args, **kwargs: None})
