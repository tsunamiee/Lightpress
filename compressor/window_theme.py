"""Theme the native Windows caption without replacing window controls."""

import ctypes
from ctypes import wintypes
import sys


def window_handle(window):
    if sys.platform != "win32":
        return None
    ancestor = ctypes.windll.user32.GetAncestor
    ancestor.argtypes = (wintypes.HWND, wintypes.UINT)
    ancestor.restype = wintypes.HWND
    return ancestor(window.winfo_id(), 2)


def colorref(value):
    red, green, blue = (int(value[index : index + 2], 16) for index in (1, 3, 5))
    return red | green << 8 | blue << 16


def apply_titlebar(window, dark, background, foreground):
    if sys.platform != "win32":
        return {}
    try:
        handle = window_handle(window)
        setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes = (wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
        setter.restype = ctypes.c_long
        result = {}
        for attribute, value in (
            (20, int(dark)),
            (35, colorref(background)),
            (36, colorref(foreground)),
        ):
            data = wintypes.DWORD(value)
            result[attribute] = setter(handle, attribute, ctypes.byref(data), ctypes.sizeof(data))
        refresh = ctypes.windll.user32.SetWindowPos
        refresh.argtypes = (
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        )
        refresh.restype = wintypes.BOOL
        refresh(handle, None, 0, 0, 0, 0, 0x0037)
        return result
    except (AttributeError, OSError):
        return {}
