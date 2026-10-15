import pytest

from app.services.resume_text import ResumeTextError, read_resume_text


def make_pdf(lines: list[str]) -> bytes:
    """A minimal one-page PDF with a real text layer (Helvetica), built by hand."""
    content = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


LINES = [
    "Asha Verma - Python Developer",
    "Education: B.Tech in Computer Science, Delhi Technological University, 2018",
    "Experience: 6 years building FastAPI and Django services at Acme Software",
    "Skills: Python, FastAPI, Django, PostgreSQL, Docker, AWS",
]


def test_reads_the_text_layer(tmp_path):
    path = tmp_path / "resume.pdf"
    path.write_bytes(make_pdf(LINES))

    text = read_resume_text(path)

    assert "B.Tech in Computer Science, Delhi Technological University, 2018" in text
    assert "  " not in text  # spaces normalised, so quotes match


def test_almost_empty_pdf_is_an_error(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_pdf(["Asha"]))
    with pytest.raises(ResumeTextError, match="scanned"):
        read_resume_text(path)


@pytest.mark.parametrize("name, data", [("resume.docx", b"PK"), ("broken.pdf", b"not a pdf")])
def test_non_pdf_or_broken_file_is_an_error(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    with pytest.raises(ResumeTextError):
        read_resume_text(path)
