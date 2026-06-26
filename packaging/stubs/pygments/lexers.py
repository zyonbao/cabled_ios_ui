"""Stub of pygments.lexers. Any lexer name (e.g. PythonLexer, BashSessionLexer)
resolves to a no-op class — only referenced from never-run shell code."""


def __getattr__(name):
    return type(name, (), {"__init__": lambda self, *args, **kwargs: None})
