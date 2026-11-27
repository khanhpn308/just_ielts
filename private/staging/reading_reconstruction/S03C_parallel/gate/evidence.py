"""Read-only source and evidence resolution for the S03C gate."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from xml.etree import ElementTree as ET
from zipfile import ZipFile


class Invalid(ValueError):
    pass


def require(condition, code, where):
    if not condition:
        raise Invalid(f"{code}: {where}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8"))


def file_sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_PROPERTY", key)
        result[key] = value
    return result


def json_data(raw):
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    digest(value)
    return value


def json_lines(raw):
    return [json_data(line) for line in raw.splitlines() if line.strip()]


def record_map(rows, name):
    require(isinstance(rows, list), "EXPECTED_LIST", name)
    result = {}
    for row in rows:
        key = row[name]
        require(isinstance(key, str) and key.strip() and key not in result,
                "DUPLICATE_OR_EMPTY_ID", key)
        result[key] = row
    return result


def shape(record, names, where):
    require(isinstance(record, dict) and set(record) == set(names.split()),
            "SCHEMA", where)


def nonblank(value):
    return isinstance(value, str) and bool(value.strip())


def rooted(root, relative):
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "PATH_ESCAPE", relative)
    path = (root / path).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file(), "PATH_ESCAPE", relative)
    return path


def xml(package, member):
    with ZipFile(package) as archive:
        return ET.fromstring(archive.read(member))


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class Sources:
    def __init__(self, workspace, inventory):
        self.workspace = workspace
        self.inventory = record_map(json_lines(inventory.read_bytes()), "source_id")
        self.paths = {}
        self.page_counts = {}
        self.native_pages = {}
        self.parts = {}

    def path(self, source_id):
        if source_id not in self.paths:
            source = self.inventory[source_id]
            require(source["source_availability"] == "AVAILABLE", "SOURCE_UNAVAILABLE", source_id)
            path = rooted(self.workspace, source["source_path"])
            require(file_sha(path) == source["source_sha256"], "SOURCE_HASH", source_id)
            self.paths[source_id] = path
        return self.paths[source_id]

    def part(self, path, member):
        key = path, member
        if key not in self.parts:
            self.parts[key] = xml(path, member)
        return self.parts[key]

    def locate(self, source_id, locator):
        """Return native text, or None for a visual PDF region."""
        path = self.path(source_id)
        kind = self.inventory[source_id]["source_format"]
        if kind == "pdf":
            native = "native_chars" in locator
            shape(locator, "page box native_chars" if native else "page box", source_id)
            if path not in self.page_counts:
                output = subprocess.run(["pdfinfo", str(path)], check=True, capture_output=True,
                                        text=True, timeout=30).stdout
                pages = re.search(r"^Pages:\s+(\d+)$", output, re.M)
                require(pages is not None, "PDF_PAGE_COUNT", source_id)
                self.page_counts[path] = int(pages[1])
            page, box = locator["page"], locator["box"]
            require(type(page) is int and 1 <= page <= self.page_counts[path],
                    "PDF_PAGE", source_id)
            require(isinstance(box, list) and len(box) == 4
                    and all(type(n) is int and 0 <= n <= 10000 for n in box)
                    and box[0] < box[2] and box[1] < box[3], "PDF_BOX", source_id)
            if not native:
                return None
            key = path, page
            if key not in self.native_pages:
                output = subprocess.run(
                    ["pdftotext", "-f", str(page), "-l", str(page), "-layout", "-nopgbrk",
                     "-enc", "UTF-8", str(path), "-"],
                    check=True, capture_output=True, timeout=30,
                )
                self.native_pages[key] = output.stdout.decode("utf-8")
            chars = locator["native_chars"]
            text = self.native_pages[key]
            require(isinstance(chars, list) and len(chars) == 2
                    and all(type(n) is int for n in chars)
                    and 0 <= chars[0] < chars[1] <= len(text), "PDF_TEXT_RANGE", source_id)
            excerpt = text[chars[0]:chars[1]]
            require(nonblank(excerpt), "PDF_TEXT_EMPTY", source_id)
            return excerpt
        if kind == "docx":
            shape(locator, "element", source_id)
            indices = locator["element"]
            require(isinstance(indices, list) and indices, "DOCX_ELEMENT", source_id)
            node = self.part(path, "word/document.xml").find(W + "body")
            for index in indices:
                require(type(index) is int and 0 <= index < len(node), "DOCX_ELEMENT", source_id)
                node = node[index]
            tokens = {W + "t": None, W + "tab": "\t", W + "br": "\n", W + "cr": "\n"}
            return "".join(tokens[child.tag] or child.text or "" for child in node.iter()
                           if child.tag in tokens)
        require(kind == "xlsx", "SOURCE_FORMAT", kind)
        shape(locator, "sheet cell", source_id)
        cell = locator["cell"]
        require(isinstance(cell, str) and re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", cell),
                "XLSX_CELL", cell)
        workbook = self.part(path, "xl/workbook.xml")
        sheets = [n for n in workbook.iter(S + "sheet") if n.get("name") == locator["sheet"]]
        require(len(sheets) == 1, "XLSX_SHEET", locator["sheet"])
        rid = sheets[0].get(R + "id")
        rels = self.part(path, "xl/_rels/workbook.xml.rels")
        targets = [rel.get("Target") for rel in rels if rel.get("Id") == rid
                   and rel.get("TargetMode") != "External"]
        require(len(targets) == 1, "XLSX_SHEET_RELATION", rid)
        target = PurePosixPath(targets[0])
        member = target.as_posix().lstrip("/") if target.is_absolute() else str(PurePosixPath("xl") / target)
        nodes = [node for node in self.part(path, member).iter(S + "c") if node.get("r") == cell]
        require(len(nodes) == 1, "XLSX_CELL", cell)
        node = nodes[0]
        if node.get("t") == "inlineStr":
            return "".join(t.text or "" for t in node.iter(S + "t"))
        value = node.findtext(S + "v", default="")
        if node.get("t") == "s":
            table = self.part(path, "xl/sharedStrings.xml")
            require(value.isdecimal() and int(value) < len(table), "XLSX_SHARED_STRING", cell)
            return "".join(t.text or "" for t in table[int(value)].iter(S + "t"))
        return value


def load_evidence(sources, evidence):
    shape(evidence, "spans assets fields", "evidence_manifest.json")
    spans = record_map(evidence["spans"], "id")
    for span_id, span in spans.items():
        shape(span, "id source_id source_sha256 locator text file", span_id)
        source_id = span["source_id"]
        location = {key: span[key] for key in ("source_id", "source_sha256", "locator")}
        require(span_id == digest(location)
                and span["source_sha256"] == sources.inventory[source_id]["source_sha256"],
                "SPAN_IDENTITY", span_id)
        native = sources.locate(source_id, span["locator"])
        require(isinstance(span["text"], str) and (native is None or native == span["text"]),
                "NATIVE_TEXT_MISMATCH", span_id)
        if span["file"] is not None:
            check_file(sources.workspace, span["file"], span_id)
    assets = record_map(evidence["assets"], "id")
    for asset_id, asset in assets.items():
        shape(asset, "id span file", asset_id)
        require(asset["span"] in spans, "ASSET_SPAN", asset_id)
        check_file(sources.workspace, asset["file"], asset_id)
    return spans, assets


def check_file(root, entry, where):
    shape(entry, "path sha256", where)
    path = rooted(root, entry["path"])
    require(path.stat().st_size > 0 and file_sha(path) == entry["sha256"], "EVIDENCE_HASH", where)
