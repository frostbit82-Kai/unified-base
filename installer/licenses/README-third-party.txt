Third-party components shipped with Unified Base
================================================

Unified Base itself is MIT-licensed: see LICENSE in the app folder.

Qt 6 and PySide6 (Qt for Python) — LGPL-3.0
    Qt-PySide6-LGPL-3.0.txt, and Qt-PySide6-GPL-3.0.txt, which the LGPL
    refers to.
    The Qt and PySide6 libraries ship unmodified, as separate shared
    libraries beside the application, so they can be replaced with a
    compatible build.
    Sources: https://download.qt.io/  and  https://download.qt.io/official_releases/QtForPython/

python-xlib — LGPL-2.1-or-later  (Linux only)
    python-xlib-LGPL-2.1.txt
    Pure Python, shipped as source.
    Source: https://github.com/python-xlib/python-xlib

CPython — Python Software Foundation License
    runtime/lib/python3.*/LICENSE.txt, which also lists the components
    Python itself carries (OpenSSL, SQLite, Tcl/Tk, zlib, libffi and others).
    The build is python-build-standalone:
    https://github.com/astral-sh/python-build-standalone

six — MIT  (a python-xlib dependency; its licence is in its dist-info)
psutil — BSD-3-Clause  (Windows only)
