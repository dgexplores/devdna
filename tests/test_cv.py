from io import BytesIO

from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from devdna.cv import CvFileError, align_cv_to_evidence, extract_cv_text
from devdna.schemas import EvidenceItem, EvidenceSnapshot, EvidenceSource


def evidence_snapshot() -> EvidenceSnapshot:
    return EvidenceSnapshot(
        schema_version="1",
        analyzer_version="test",
        target_role="python_backend_developer",
        rubric_version="python_backend_developer:v1",
        repositories_analyzed=1,
        items=[
            EvidenceItem(
                key="python.project",
                category="language",
                claim="Python project files are present.",
                repository="octocat/backend",
                sources=[
                    EvidenceSource(
                        repository="octocat/backend",
                        path="pyproject.toml",
                        url="https://github.com/octocat/backend/blob/main/pyproject.toml",
                    )
                ],
            )
        ],
    )


def docx_bytes(text: str) -> bytes:
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    safe_text = text.replace("(", "").replace(")", "")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({safe_text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_extracts_docx_and_pdf_text() -> None:
    assert "Python" in extract_cv_text(
        "resume.docx",
        docx_bytes("Python FastAPI"),
        max_pages=10,
        max_characters=10_000,
    )
    assert "Python" in extract_cv_text(
        "resume.pdf",
        pdf_bytes("Python FastAPI"),
        max_pages=10,
        max_characters=10_000,
    )


def test_alignment_never_promotes_cv_only_claims() -> None:
    alignment = align_cv_to_evidence(
        "octocat",
        "resume.docx",
        "Python FastAPI Docker",
        evidence_snapshot(),
    )

    by_skill = {skill.skill: skill for skill in alignment.skills}
    assert by_skill["Python"].status == "verified"
    assert by_skill["Python"].evidence_sources
    assert by_skill["FastAPI"].status == "self_reported_unverified"
    assert by_skill["Container delivery"].status == "self_reported_unverified"
    assert alignment.suggested_summary == "Public GitHub work verifies Python."
    assert "FastAPI" not in alignment.suggested_summary
    assert "Container delivery" not in alignment.suggested_summary


def test_extraction_rejects_unsupported_empty_and_bounded_files() -> None:
    for filename, content in (
        ("resume.txt", b"Python"),
        ("resume.docx", b"not-a-docx"),
        ("resume.pdf", b"not-a-pdf"),
    ):
        try:
            extract_cv_text(filename, content, max_pages=1, max_characters=1000)
        except CvFileError:
            pass
        else:
            raise AssertionError(f"{filename} should be rejected")

    try:
        extract_cv_text(
            "resume.docx",
            docx_bytes("Python " * 300),
            max_pages=1,
            max_characters=1000,
        )
    except CvFileError as error:
        assert "character limit" in str(error)
    else:
        raise AssertionError("oversized extracted text should be rejected")


def test_pdf_page_limit_is_enforced_before_extraction() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)

    try:
        extract_cv_text("resume.pdf", output.getvalue(), max_pages=1, max_characters=1000)
    except CvFileError as error:
        assert "at most 1 pages" in str(error)
    else:
        raise AssertionError("page-bounded PDF should be rejected")
