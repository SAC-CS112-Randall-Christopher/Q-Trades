"""Select bounded logical processors on distinct Windows physical cores."""

import ctypes
import os
import struct


def physical_core_masks() -> list[int]:
    if os.name != "nt" or ctypes.sizeof(ctypes.c_void_p) != 8:
        raise OSError("Physical-core placement requires native 64-bit Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.GetLogicalProcessorInformationEx
    query.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    query.restype = ctypes.c_int
    size = ctypes.c_ulong()
    query(0, None, ctypes.byref(size))  # RelationProcessorCore, one record per physical core.
    if not 0 < size.value <= 1024**2:
        raise OSError("Processor topology exceeds the supported bounded query")
    buffer = ctypes.create_string_buffer(size.value)
    if not query(0, buffer, ctypes.byref(size)):
        raise OSError("Cannot observe current physical-core topology")
    return decode_core_masks(buffer.raw[: size.value])


def decode_core_masks(raw: bytes) -> list[int]:
    masks: list[int] = []
    offset = 0
    while offset < len(raw):
        if len(raw) - offset < 48:
            raise OSError("Incomplete processor topology record")
        relationship, size = struct.unpack_from("<II", raw, offset)
        groups = struct.unpack_from("<H", raw, offset + 30)[0]
        mask, group = struct.unpack_from("<QH", raw, offset + 32)
        if (
            relationship != 0
            or size != 48
            or offset + size > len(raw)
            or groups != 1
            or group != 0
            or not mask
            or any(mask & previous for previous in masks)
        ):
            raise OSError("Unsupported processor-group topology; no allocation inferred")
        masks.append(mask)
        offset += size
    if not masks:
        raise OSError("Physical-core topology is empty")
    return masks


def distinct_processors(available: int, cores: list[int], count: int = 2) -> int:
    selected = 0
    for core in cores:
        eligible = available & core
        if eligible:
            selected |= eligible & -eligible
            if selected.bit_count() == count:
                return selected
    raise OSError("Available allocation does not cover the required distinct physical cores")
