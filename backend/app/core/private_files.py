"""Private local files and inter-process locks on POSIX and Windows."""
from __future__ import annotations

import ctypes
import os
import re
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _current_sid() -> str:
    result = subprocess.check_output(['whoami', '/user', '/fo', 'csv', '/nh']).decode('ascii', errors='ignore')
    match = re.search(r'S-1-[0-9-]+', result)
    if match is None:
        raise OSError('Cannot determine Windows security identity')
    return match.group()


@lru_cache(maxsize=1)
def _windows_api():
    if sys.platform != "win32":
        raise OSError("Windows security API is unavailable")
    from ctypes import wintypes
    api = ctypes.WinDLL('advapi32', use_last_error=True)
    pointer = ctypes.c_void_p
    api.GetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                         pointer, pointer, pointer, pointer, ctypes.POINTER(pointer)]
    api.GetSecurityInfo.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                   pointer, pointer, pointer, pointer, ctypes.POINTER(pointer)]
    api.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [pointer, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(pointer), pointer]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.POINTER(pointer), pointer]
    api.GetSecurityDescriptorDacl.argtypes = [pointer, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(pointer), ctypes.POINTER(wintypes.BOOL)]
    api.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
                                        pointer, pointer, pointer, pointer]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    return api, kernel


def _windows_descriptor(path: Path, fd: int | None = None) -> str:
    if sys.platform != "win32":
        raise OSError("Windows security API is unavailable")
    api, kernel = _windows_api()
    descriptor = ctypes.c_void_p()
    if fd is None:
        code = api.GetNamedSecurityInfoW(str(path), 1, 5, None, None, None, None, ctypes.byref(descriptor))
    else:
        import msvcrt
        code = api.GetSecurityInfo(msvcrt.get_osfhandle(fd), 1, 5, None, None, None, None, ctypes.byref(descriptor))
    if code:
        raise OSError(code, 'Cannot inspect private file permissions')
    result = ctypes.c_void_p()
    try:
        if not api.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 5, ctypes.byref(result), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return ctypes.wstring_at(result)
    finally:
        if result:
            kernel.LocalFree(result)
        kernel.LocalFree(descriptor)


def require_private(path: Path, *, directory: bool = False, fd: int | None = None) -> None:
    info = os.fstat(fd) if fd is not None else path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise OSError('Private path must not be a link or reparse point')
    if sys.platform == 'win32':
        descriptor = _windows_descriptor(path, fd)
        sid = _current_sid()
        owner = descriptor.split('D:', 1)[0]
        entries = re.findall(r'\(([^()]*)\)', descriptor)
        if owner != 'O:' + sid or not entries:
            raise OSError('Invalid private file owner or ACL')
        for entry in entries:
            fields = entry.split(';')
            if len(fields) != 6 or fields[0] != 'A' or fields[2] not in {'FA', '0x1f01ff'} or fields[5] != sid or 'IO' in fields[1]:
                raise OSError('Private ACL grants access to another identity')
    elif info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600):
        raise OSError('Invalid private file owner or permissions')


def protect_private(path: Path, *, directory: bool = False) -> None:
    info = path.lstat()
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise OSError('Refusing private permissions on links or special files')
    if sys.platform == 'win32':
        from ctypes import wintypes
        api, kernel = _windows_api()
        descriptor = ctypes.c_void_p()
        flags = 'OICI' if directory else ''
        sddl = f'D:P(A;{flags};FA;;;{_current_sid()})'
        if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            present, defaulted = wintypes.BOOL(), wintypes.BOOL()
            dacl = ctypes.c_void_p()
            if not api.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
                raise ctypes.WinError(ctypes.get_last_error())
            code = api.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None)
            if code:
                raise OSError(code, 'Cannot protect private path')
        finally:
            kernel.LocalFree(descriptor)
    else:
        path.chmod(0o700 if directory else 0o600)
    require_private(path, directory=directory)


@contextmanager
def exclusive_lock(fd: int):
    if sys.platform == 'win32':
        import msvcrt
        position = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if error.errno not in (13, 36):
                    raise
                time.sleep(0.05)
        try:
            os.lseek(fd, position, os.SEEK_SET)
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            os.lseek(fd, position, os.SEEK_SET)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
