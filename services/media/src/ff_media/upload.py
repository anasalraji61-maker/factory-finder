"""Streaming multipart/form-data reader with a hard size cap (never buffers more than the limit).

Only the ``file`` (exactly one) and ``kind`` parts are read; the client filename and part content-type are ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser, parse_options_header

from ff_media.errors import BadRequest, FileTooLarge, UnsupportedMediaType

OVERHEAD = 64 * 1024  # multipart framing + small text fields on top of the file limit
MAX_KIND_BYTES = 64


@dataclass
class Upload:
    data: bytes
    kind: str | None


async def read_upload(request: Request, max_file_bytes: int) -> Upload:
    ctype, params = parse_options_header(request.headers.get("content-type", ""))
    if ctype.lower() != b"multipart/form-data" or not params.get(b"boundary"):
        raise UnsupportedMediaType("Send multipart/form-data with a `file` field")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_file_bytes + OVERHEAD:
        raise FileTooLarge(f"Upload exceeds {max_file_bytes} bytes", {"max_bytes": max_file_bytes})

    files: list[bytearray] = []
    fields: dict[str, bytearray] = {}
    state: dict = {"name": None, "is_file": False, "hname": b"", "hvalue": b"", "ignore": False}
    parts = {"n": 0}

    def too_large() -> FileTooLarge:
        return FileTooLarge(f"Upload exceeds {max_file_bytes} bytes", {"max_bytes": max_file_bytes})

    def on_part_begin() -> None:
        parts["n"] += 1
        if parts["n"] > 8:
            raise BadRequest("Too many form parts")
        state.update(name=None, is_file=False, hname=b"", hvalue=b"", ignore=False)

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["hname"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state["hvalue"] += data[start:end]

    def on_header_end() -> None:
        if state["hname"].lower() == b"content-disposition":
            _, p = parse_options_header(state["hvalue"])
            state["name"] = p.get(b"name", b"").decode("utf-8", "replace")
            state["is_file"] = b"filename" in p
        state["hname"], state["hvalue"] = b"", b""

    def on_headers_finished() -> None:
        name = state["name"]
        if name == "file":
            files.append(bytearray())
        elif name == "kind":
            fields["kind"] = bytearray()
        else:
            state["ignore"] = True

    def on_part_data(data: bytes, start: int, end: int) -> None:
        if state["ignore"]:
            return
        if state["name"] == "file":
            buf = files[-1]
            if len(buf) + (end - start) > max_file_bytes:
                raise too_large()
            buf += data[start:end]
        else:
            buf = fields["kind"]
            if len(buf) + (end - start) > MAX_KIND_BYTES:
                raise BadRequest("`kind` is too long")
            buf += data[start:end]

    parser = MultipartParser(
        params[b"boundary"],
        {
            "on_part_begin": on_part_begin, "on_header_field": on_header_field,
            "on_header_value": on_header_value, "on_header_end": on_header_end,
            "on_headers_finished": on_headers_finished, "on_part_data": on_part_data,
        },
        max_size=max_file_bytes + OVERHEAD,
    )  # fmt: skip
    total = 0
    try:
        async for chunk in request.stream():
            total += len(chunk)
            if total > max_file_bytes + OVERHEAD:
                raise too_large()
            parser.write(chunk)
        parser.finalize()
    except MultipartParseError as e:
        raise BadRequest("Malformed multipart body") from e
    if len(files) != 1:
        raise BadRequest("Exactly one `file` field is required", {"files": len(files)})
    kind = fields["kind"].decode("utf-8", "replace").strip() if "kind" in fields else None
    return Upload(bytes(files[0]), kind or None)
