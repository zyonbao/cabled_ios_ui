"""slide6_console — PySide6 desktop console for controlling USB-connected iOS devices.

Feature-parity desktop counterpart of `web_console`: it mirrors a device screen
via WDA's MJPEG broadcaster and forwards mouse gestures and host-keyboard input
back to the device. Unlike the browser console, it runs in-process and calls
`executor_ios.toolkit_api` directly (no HTTP layer), and can detect/launch the
iOS 17+ XPC tunnel with system authorization.
"""
