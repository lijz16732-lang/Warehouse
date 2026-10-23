# -*- coding: utf-8 -*-
"""纯 ctypes 抓取全屏并保存 PNG（无需 PIL / PowerShell）。"""

import ctypes
import sys
import zlib
from ctypes import wintypes


def capture(path):
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.SetProcessDPIAware()
    w = user32.GetSystemMetrics(0)
    h = user32.GetSystemMetrics(1)

    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    hdc = user32.GetDC(None)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    mem = gdi32.CreateCompatibleDC(hdc)
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                             ctypes.c_uint32]
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPPM", ctypes.c_int32),
                    ("biYPPM", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bmih = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint]
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmih), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC(None, hdc)

    raw = bytearray()
    stride = w * 4
    data = bytes(buf)
    for y in range(h):
        row = bytearray(data[y * stride:(y + 1) * stride])
        for x in range(0, stride, 4):
            row[x], row[x + 2] = row[x + 2], row[x]  # BGRA -> RGBA
        raw.append(0)
        raw.extend(row)

    def chunk(t, d):
        return (len(d).to_bytes(4, "big") + t + d +
                (zlib.crc32(t + d) & 0xffffffff).to_bytes(4, "big"))

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") +
                 bytes([8, 6, 0, 0, 0]))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(out)
    return path


def capture_window(title_sub, path):
    """按标题找到窗口，置前并截取该窗口区域。"""
    import time
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    user32.SetProcessDPIAware()
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    hwnd = None
    for _ in range(60):
        hwnd = user32.FindWindowW(None, None)
        found = None
        while hwnd:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if title_sub in buf.value and user32.IsWindowVisible(hwnd):
                found = hwnd
                break
            hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT
        if found:
            hwnd = found
            break
        time.sleep(0.5)
    if not hwnd:
        raise RuntimeError("window not found: %s" % title_sub)

    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(1.2)

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    x, y = rect.left, rect.top
    w, h = rect.right - rect.left, rect.bottom - rect.top

    hdc = user32.GetDC(None)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    mem = gdi32.CreateCompatibleDC(hdc)
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject(mem, bmp)
    gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int,
                             ctypes.c_uint32]
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, x, y, 0x00CC0020)

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPPM", ctypes.c_int32),
                    ("biYPPM", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bmih = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, ctypes.c_uint,
                                ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_uint]
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmih), 0)

    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, hdc)

    raw = bytearray()
    stride = w * 4
    data = bytes(buf)
    for y2 in range(h):
        row = bytearray(data[y2 * stride:(y2 + 1) * stride])
        for x2 in range(0, stride, 4):
            row[x2], row[x2 + 2] = row[x2 + 2], row[x2]
        raw.append(0)
        raw.extend(row)

    def chunk(t, d):
        return (len(d).to_bytes(4, "big") + t + d +
                (zlib.crc32(t + d) & 0xffffffff).to_bytes(4, "big"))

    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") +
                 bytes([8, 6, 0, 0, 0]))
    out += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    out += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(out)
    return path


if __name__ == "__main__":
    title = sys.argv[2] if len(sys.argv) > 2 else "仓管家"
    print("saved:", capture_window(title, sys.argv[1]))
