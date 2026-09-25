from pathlib import Path

from my_org.file_db.parsers.csv_parser import (
    count_rows,
    detect_delimiter,
    detect_encoding,
    parse_schema,
    read_rows,
    transcode_to_utf8,
)
from my_org.file_db.parsers.schema import infer_column_type

ZH = "\n".join(["编号,姓名,城市"] + [f"{i},张三{i},北京" for i in range(200)])


def test_detect_encoding_utf8_and_gbk(tmp_path):
    p_utf = tmp_path / "u.csv"
    p_utf.write_text(ZH, encoding="utf-8")
    assert detect_encoding(str(p_utf)) == "utf-8"

    p_gbk = tmp_path / "g.csv"
    p_gbk.write_bytes(ZH.encode("gbk"))
    assert detect_encoding(str(p_gbk)) == "gbk"  # chardet 'GB2312' normalized

    p_ascii = tmp_path / "a.csv"
    p_ascii.write_text("a,b\n1,2\n", encoding="ascii")
    assert detect_encoding(str(p_ascii)) == "utf-8"  # 'ascii' normalized


def test_detect_delimiters(tmp_path):
    cases = {
        ",": "a,b,c\nd,e,f\n" * 5,
        ";": "a;b;c\nd;e;f\n" * 5,
        "\t": "a\tb\tc\nd\te\tf\n" * 5,
        "|": "a|b|c\nd|e|f\n" * 5,
        " ": "a b c\nd e f\n" * 5,
    }
    for delim, text in cases.items():
        p = tmp_path / f"d{ord(delim)}.csv"
        p.write_text(text, encoding="utf-8")
        assert detect_delimiter(str(p), "utf-8") == delim


def test_infer_column_types():
    assert infer_column_type(["1", "2", "-3"]) == ("integer", None)
    assert infer_column_type(["1.5", "2"]) == ("float", None)
    assert infer_column_type(["true", "FALSE", "yes"]) == ("boolean", None)
    assert infer_column_type(["t", "f"]) == ("boolean", None)
    assert infer_column_type(["2026-09-25", "2026-01-01"]) == ("datetime", "%Y-%m-%d")
    assert infer_column_type(["2026-09-25 10:30:00"]) == ("datetime", "%Y-%m-%d %H:%M:%S")
    assert infer_column_type(["abc", "1"]) == ("string", None)
    assert infer_column_type([]) == ("string", None)


def test_parse_schema_samples(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("a,a,b,x\n1,2,hello,1\n,4,world,2\n3,6,,3\n", encoding="utf-8")
    fs = parse_schema(str(p), "utf-8", ",")

    assert [c.name for c in fs.columns] == ["a", "a_2", "b", "x"]
    col_a = fs.columns[0]
    assert col_a.column_type == "integer"
    assert col_a.sample_values == ["1", "3"]
    assert col_a.is_nullable is True  # has empty value in window
    assert fs.columns[1].column_type == "integer"
    assert fs.columns[2].sample_values == ["hello", "world"]
    assert fs.columns[3].is_nullable is False
    assert fs.columns[3].column_type == "integer"


def test_count_and_read_rows(tmp_path):
    p = tmp_path / "r.csv"
    lines = ["id,name"] + [f"{i},n{i}" for i in range(5)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert count_rows(str(p), "utf-8", ",") == 5
    assert read_rows(str(p), "utf-8", ",", limit=2) == [["0", "n0"], ["1", "n1"]]
    assert read_rows(str(p), "utf-8", ",", limit=10, offset=4) == [["4", "n4"]]
    assert read_rows(str(p), "utf-8", ",", limit=10, offset=99) == []

    p2 = tmp_path / "e.csv"
    p2.write_text("a,b\n1,\n", encoding="utf-8")
    assert read_rows(str(p2), "utf-8", ",", limit=10) == [["1", None]]


def test_transcode_to_utf8(tmp_path):
    text = "\n".join(["编号,姓名"] + [f"{i},张三{i}" for i in range(50)]) + "\n"
    p = tmp_path / "g.csv"
    p.write_bytes(text.encode("gbk"))

    out = transcode_to_utf8(str(p), "gbk")
    assert out.endswith(".utf8")
    assert Path(out).read_text(encoding="utf-8") == text
