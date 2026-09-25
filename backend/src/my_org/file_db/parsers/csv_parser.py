"""CSV parsing: encoding/delimiter detection, schema, rows, UTF-8 transcoding."""

import csv
import itertools

import chardet

from .schema import FileSchema, build_columns, unique_names

_ENCODING_NORMALIZE = {
    "ascii": "utf-8",
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "utf-16": "utf-16",
    "utf16": "utf-16",
    "gb2312": "gbk",
    "gbk": "gbk",
    "gb18030": "gbk",
    "iso-8859-1": "latin-1",
    "latin-1": "latin-1",
    "latin1": "latin-1",
    "windows-1252": "latin-1",
}

_DELIMITERS = [",", ";", "\t", "|", " "]


def detect_encoding(path: str) -> str:
    with open(path, "rb") as f:
        sample = f.read(512 * 1024)
    detected = (chardet.detect(sample) or {}).get("encoding") or ""
    return _ENCODING_NORMALIZE.get(detected.lower(), "utf-8")


def detect_delimiter(path: str, encoding: str) -> str:
    with open(path, encoding=encoding, newline="") as f:
        sample = "".join(f.readline() for _ in range(10))
    try:
        return csv.Sniffer().sniff(sample, delimiters="".join(_DELIMITERS)).delimiter
    except csv.Error:
        counts = {d: 0 for d in _DELIMITERS}
        for line in sample.splitlines()[:10]:
            for d in _DELIMITERS:
                counts[d] += line.count(d)
        return max(counts, key=counts.get)


def parse_schema(path: str, encoding: str, delimiter: str) -> FileSchema:
    header, rows = _split(path, encoding, delimiter)
    names = unique_names(header)
    columns = build_columns(names, itertools.islice(rows, 200))
    return FileSchema(columns=columns, sheets=[], row_count=None)


def count_rows(path: str, encoding: str, delimiter: str) -> int:
    return sum(1 for _ in _data_rows(path, encoding, delimiter))


def read_rows(
    path: str, encoding: str, delimiter: str, limit: int = 100, offset: int = 0
) -> list[list[str | None]]:
    skipped = itertools.islice(_data_rows(path, encoding, delimiter), offset, None)
    return list(itertools.islice(skipped, limit))


def transcode_to_utf8(path: str, encoding: str) -> str:
    out = f"{path}.utf8"
    with open(path, encoding=encoding, newline="") as src, open(
        out, "w", encoding="utf-8", newline=""
    ) as dst:
        for chunk in iter(lambda: src.read(65536), ""):
            dst.write(chunk)
    return out


def _split(path: str, encoding: str, delimiter: str):
    it = _reader(path, encoding, delimiter)
    header = [str(v) if v is not None else "" for v in next(it, [])]
    return header, (row for row in it if not _is_empty(row))


def _data_rows(path: str, encoding: str, delimiter: str):
    it = _reader(path, encoding, delimiter)
    next(it, None)  # header
    return (row for row in it if not _is_empty(row))


def _reader(path: str, encoding: str, delimiter: str):
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            yield [v if v != "" else None for v in row]


def _is_empty(row: list) -> bool:
    return all(v is None or (isinstance(v, str) and v.strip() == "") for v in row)
