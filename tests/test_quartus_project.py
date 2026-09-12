import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUARTUS = ROOT / "quartus"
HDL = ROOT / "hdl"
QSF = QUARTUS / "CPUFrFr.qsf"
FILE_ASSIGNMENT = re.compile(
    r'^\s*set_global_assignment\s+-name\s+'
    r'(SDC_FILE|SYSTEMVERILOG_FILE|VERILOG_FILE|MIF_FILE)\s+'
    r'(?:"([^"]+)"|\{([^}]+)\}|(\S+))'
)
LOCAL_COPY_SUFFIXES = {".sv", ".svh", ".v", ".mif", ".sdc"}


def _file_assignments() -> list[tuple[str, str]]:
    assignments = [
        (match[1], match[2] or match[3] or match[4])
        for line in QSF.read_text(encoding="utf-8").splitlines()
        if (match := FILE_ASSIGNMENT.match(line))
    ]
    assert assignments, "No source or constraint assignments found in the QSF"
    return assignments


def test_quartus_file_assignments_resolve_from_project_directory() -> None:
    for kind, relative_path in _file_assignments():
        assert (QUARTUS / relative_path).resolve().is_file(), f"{kind}: {relative_path}"


def test_quartus_rtl_assignments_use_canonical_hdl_sources() -> None:
    rtl_kinds = {"SYSTEMVERILOG_FILE", "VERILOG_FILE"}
    for kind, relative_path in _file_assignments():
        if kind in rtl_kinds:
            assert HDL.resolve() in (QUARTUS / relative_path).resolve().parents


def test_quartus_directory_has_no_local_rtl_constraint_or_mif_copies() -> None:
    copies = sorted(
        path.name for path in QUARTUS.iterdir()
        if path.is_file() and path.suffix.lower() in LOCAL_COPY_SUFFIXES
    )
    assert copies == []


def test_quartus_project_references_every_rtl_source() -> None:
    referenced = {
        (QUARTUS / path).resolve()
        for kind, path in _file_assignments()
        if kind in {"SYSTEMVERILOG_FILE", "VERILOG_FILE"}
    }
    on_disk = {path.resolve() for path in HDL.glob("*.sv")} | {
        path.resolve() for path in HDL.glob("*.v")
    }

    missing = sorted(path.name for path in on_disk - referenced)
    assert not missing, f"RTL sources missing from the Quartus project: {missing}"
