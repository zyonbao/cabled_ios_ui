"""Build-time stub for `IPython` (see packaging/stubs/README.md).

Only `IPython.start_ipython` is referenced (by pymobiledevice3.utils.
start_ipython_shell), an interactive entry point the packaged GUI never calls."""


def start_ipython(*args, **kwargs):
    raise RuntimeError("IPython shell is not available in this packaged build")
