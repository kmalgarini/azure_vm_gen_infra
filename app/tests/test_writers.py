"""Tests for the TXT and XML writer functions."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import pytest
from generator.writers.txt import write_bcr, write_zdn, write_zro
from generator.writers.xml import write_940, write_945, write_945osr

NOW = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)
DTR = "DTR-20260419-00001"
BATCH = "BCR-20260419-001"
DTR_REGEX = re.compile(r"DTR[:\s]*(\S+)")


# ---------------------------------------------------------------------------
# BCR (multi-DTR batch file)
# ---------------------------------------------------------------------------

def test_write_bcr_filename_pattern(tmp_path):
    path = write_bcr(str(tmp_path), BATCH, [DTR], NOW)
    assert path.name.startswith(f"BCR_{BATCH}_")
    assert path.name.endswith(".txt")


def test_write_bcr_file_is_created(tmp_path):
    path = write_bcr(str(tmp_path), BATCH, [DTR], NOW)
    assert path.exists()


def test_write_bcr_contains_batch_header(tmp_path):
    path = write_bcr(str(tmp_path), BATCH, [DTR], NOW)
    assert f"BATCH: {BATCH}" in path.read_text()


def test_write_bcr_contains_all_dtr_lines(tmp_path):
    dtrs = [f"DTR-20260419-0000{i}" for i in range(1, 4)]
    path = write_bcr(str(tmp_path), BATCH, dtrs, NOW)
    content = path.read_text()
    for d in dtrs:
        assert f"DTR: {d}" in content


def test_write_bcr_all_dtrs_findall_extractable(tmp_path):
    dtrs = [f"DTR-20260419-0000{i}" for i in range(1, 4)]
    path = write_bcr(str(tmp_path), BATCH, dtrs, NOW)
    found = DTR_REGEX.findall(path.read_text())
    assert set(found) == set(dtrs)


def test_write_bcr_single_dtr(tmp_path):
    path = write_bcr(str(tmp_path), BATCH, [DTR], NOW)
    found = DTR_REGEX.findall(path.read_text())
    assert found == [DTR]


def test_write_bcr_contains_initiated_status(tmp_path):
    path = write_bcr(str(tmp_path), BATCH, [DTR], NOW)
    assert "STATUS: INITIATED" in path.read_text()


# ---------------------------------------------------------------------------
# ZRO
# ---------------------------------------------------------------------------

def test_write_zro_filename_pattern(tmp_path):
    path = write_zro(str(tmp_path), DTR, NOW)
    assert path.name.startswith(f"ZRO_{DTR}_")
    assert path.name.endswith(".txt")


def test_write_zro_dtr_regex_match(tmp_path):
    path = write_zro(str(tmp_path), DTR, NOW)
    match = DTR_REGEX.search(path.read_text())
    assert match is not None
    assert match.group(1) == DTR


def test_write_zro_contains_warehouse(tmp_path):
    path = write_zro(str(tmp_path), DTR, NOW)
    assert "WAREHOUSE: WH-001" in path.read_text()


def test_write_zro_contains_acknowledged_status(tmp_path):
    path = write_zro(str(tmp_path), DTR, NOW)
    assert "STATUS: ACKNOWLEDGED" in path.read_text()


# ---------------------------------------------------------------------------
# ZDN
# ---------------------------------------------------------------------------

def test_write_zdn_filename_pattern(tmp_path):
    path = write_zdn(str(tmp_path), DTR, NOW)
    assert path.name.startswith(f"ZDN_{DTR}_")
    assert path.name.endswith(".txt")


def test_write_zdn_dtr_regex_match(tmp_path):
    path = write_zdn(str(tmp_path), DTR, NOW)
    match = DTR_REGEX.search(path.read_text())
    assert match is not None
    assert match.group(1) == DTR


def test_write_zdn_contains_dispatched_status(tmp_path):
    path = write_zdn(str(tmp_path), DTR, NOW)
    assert "STATUS: DISPATCHED" in path.read_text()


def test_write_zdn_contains_tracking_ref(tmp_path):
    path = write_zdn(str(tmp_path), DTR, NOW)
    assert f"TRACKING: TRK-{DTR}" in path.read_text()


# ---------------------------------------------------------------------------
# 940 XML
# ---------------------------------------------------------------------------

def test_write_940_filename_pattern(tmp_path):
    path = write_940(str(tmp_path), DTR, NOW)
    assert path.name.startswith(f"940_{DTR}_")
    assert path.name.endswith(".xml")


def test_write_940_is_valid_xml(tmp_path):
    path = write_940(str(tmp_path), DTR, NOW)
    ET.parse(path)  # raises ParseError if invalid


def test_write_940_dtr_xpath_extractable(tmp_path):
    path = write_940(str(tmp_path), DTR, NOW)
    nodes = ET.parse(path).findall(".//DTRNumber")
    assert len(nodes) == 1
    assert nodes[0].text == DTR


def test_write_940_document_type(tmp_path):
    path = write_940(str(tmp_path), DTR, NOW)
    assert ET.parse(path).find(".//DocumentType").text == "940"


# ---------------------------------------------------------------------------
# 945 XML
# ---------------------------------------------------------------------------

def test_write_945_filename_pattern(tmp_path):
    path = write_945(str(tmp_path), DTR, NOW)
    assert path.name.startswith(f"945_{DTR}_")
    assert path.name.endswith(".xml")


def test_write_945_dtr_xpath_extractable(tmp_path):
    path = write_945(str(tmp_path), DTR, NOW)
    nodes = ET.parse(path).findall(".//DTRNumber")
    assert len(nodes) == 1
    assert nodes[0].text == DTR


def test_write_945_document_type(tmp_path):
    path = write_945(str(tmp_path), DTR, NOW)
    assert ET.parse(path).find(".//DocumentType").text == "945"


# ---------------------------------------------------------------------------
# 945OSR XML
# ---------------------------------------------------------------------------

def test_write_945osr_filename_pattern(tmp_path):
    path = write_945osr(str(tmp_path), DTR, NOW)
    assert path.name.startswith(f"945OSR_{DTR}_")
    assert path.name.endswith(".xml")


def test_write_945osr_dtr_xpath_extractable(tmp_path):
    path = write_945osr(str(tmp_path), DTR, NOW)
    nodes = ET.parse(path).findall(".//DTRNumber")
    assert len(nodes) == 1
    assert nodes[0].text == DTR


def test_write_945osr_completed_status(tmp_path):
    path = write_945osr(str(tmp_path), DTR, NOW)
    assert ET.parse(path).find(".//OrderStatus").text == "COMPLETED"


def test_write_945osr_document_type(tmp_path):
    path = write_945osr(str(tmp_path), DTR, NOW)
    assert ET.parse(path).find(".//DocumentType").text == "945OSR"


# ---------------------------------------------------------------------------
# Timestamp format is compact (safe for filenames)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("writer,prefix", [
    (lambda d, dtr, t: write_zro(d, dtr, t), "ZRO"),
    (lambda d, dtr, t: write_zdn(d, dtr, t), "ZDN"),
    (lambda d, dtr, t: write_940(d, dtr, t), "940"),
    (lambda d, dtr, t: write_945(d, dtr, t), "945_"),
    (lambda d, dtr, t: write_945osr(d, dtr, t), "945OSR"),
])
def test_filename_contains_no_colons(tmp_path, writer, prefix):
    path = writer(str(tmp_path), DTR, NOW)
    assert ":" not in path.name
