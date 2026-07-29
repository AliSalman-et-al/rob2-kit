"""Shared deterministic ZIP serialization for derived outputs."""

from __future__ import annotations

import io
from collections.abc import Callable, Mapping
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

MemberTransform = Callable[[str, bytes], bytes]


def write_deterministic_zip(
    members: Mapping[str, bytes],
    *,
    transform: MemberTransform | None = None,
) -> bytes:
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path, original in sorted(members.items()):
            content = transform(path, original) if transform is not None else original
            info = ZipInfo(path, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    return stream.getvalue()
