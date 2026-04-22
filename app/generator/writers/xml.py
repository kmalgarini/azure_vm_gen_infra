"""XML file writers: 940, 945, 945OSR.

All elements use ``<DTRNumber>`` so ``restocking_monitor`` can extract the DTR
value with the XPath ``//DTRNumber/text()``.
"""
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def _ts(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%S")


def _iso(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_xml(path: Path, root: ET.Element) -> Path:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    with open(path, "wb") as fh:
        tree.write(fh, encoding="utf-8", xml_declaration=True)
    return path


def write_940(outdir: str, dtr: str, now: datetime) -> Path:
    """EDI 940 Warehouse Shipping Order."""
    root = ET.Element("WarehouseShippingOrder")

    hdr = ET.SubElement(root, "Header")
    ET.SubElement(hdr, "DocumentType").text = "940"
    ET.SubElement(hdr, "GeneratedAt").text = _iso(now)

    order = ET.SubElement(root, "Order")
    ET.SubElement(order, "DTRNumber").text = dtr
    ET.SubElement(order, "WarehouseID").text = "WH-001"
    ET.SubElement(order, "ShipTo").text = "DEST-001"

    return _write_xml(Path(outdir) / f"940_{dtr}_{_ts(now)}.xml", root)


def write_945(outdir: str, dtr: str, now: datetime) -> Path:
    """EDI 945 Warehouse Shipping Advice."""
    root = ET.Element("WarehouseShippingAdvice")

    hdr = ET.SubElement(root, "Header")
    ET.SubElement(hdr, "DocumentType").text = "945"
    ET.SubElement(hdr, "GeneratedAt").text = _iso(now)

    detail = ET.SubElement(root, "ShipmentDetail")
    ET.SubElement(detail, "DTRNumber").text = dtr
    ET.SubElement(detail, "ShipDate").text = _iso(now)
    ET.SubElement(detail, "Carrier").text = "CARRIER-42"

    return _write_xml(Path(outdir) / f"945_{dtr}_{_ts(now)}.xml", root)


def write_945osr(outdir: str, dtr: str, now: datetime) -> Path:
    """945 Order Status Response — final confirmation."""
    root = ET.Element("OrderStatusResponse")

    hdr = ET.SubElement(root, "Header")
    ET.SubElement(hdr, "DocumentType").text = "945OSR"
    ET.SubElement(hdr, "GeneratedAt").text = _iso(now)

    status = ET.SubElement(root, "Status")
    ET.SubElement(status, "DTRNumber").text = dtr
    ET.SubElement(status, "OrderStatus").text = "COMPLETED"
    ET.SubElement(status, "CompletedAt").text = _iso(now)

    return _write_xml(Path(outdir) / f"945OSR_{dtr}_{_ts(now)}.xml", root)
