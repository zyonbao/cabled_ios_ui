"""Stub of pygnuutils.ls. `LsStub` is used as a base class at import time in
afc.py (`class AfcLsStub(LsStub)`); `Ls` is only instantiated by the never-run
`ls` shell command."""


class Ls:
    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return None


class LsStub:
    pass
