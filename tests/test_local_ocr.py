from io import BytesIO
import subprocess

import pytest
from reportlab.pdfgen import canvas

from app.agents.pilot import extract_document
from app.agents.ocr import image_pdf, local_ocr
from app.agents.screening import ScreeningError


TEXT = "Python developer with SQL and Django skills. Built REST APIs and automated tests."


def native_pdf():
    output = BytesIO()
    doc = canvas.Canvas(output, pagesize=(700, 300))
    doc.setFont("Helvetica", 18)
    doc.drawString(30, 220, "Python developer with SQL and Django skills.")
    doc.drawString(30, 180, "Built REST APIs and automated tests.")
    doc.drawString(30, 140, "Education: Bachelor of Computer Science.")
    doc.save()
    return output.getvalue()


def photo():
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(native_pdf())
    page = pdf[0]
    bitmap = page.render(scale=2)
    image = bitmap.to_pil()
    try:
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()
        bitmap.close()
        page.close()
        pdf.close()


def test_native_text_does_not_invoke_ocr(monkeypatch):
    def forbidden(*args):
        pytest.fail("Text PDF should not use OCR")
    monkeypatch.setattr("app.agents.ocr.local_ocr", forbidden)
    result = extract_document(native_pdf(), ".pdf")
    assert result["method"] == "native_text" and not result["ocr_pages"]
    assert "Python" in result["text"]


def test_real_local_photo_and_mixed_pdf_ocr():
    # The real child process disables sockets; these bundled-model checks are offline.
    png = photo()
    result = extract_document(png, ".png")
    assert result["ocr_pages"] == [1]
    assert all(skill in result["text"] for skill in ("Python", "SQL", "Django"))
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.append(BytesIO(native_pdf()))
    writer.append(BytesIO(image_pdf(png)))
    output = BytesIO()
    writer.write(output)
    result = extract_document(output.getvalue(), ".pdf")
    assert result["ocr_pages"] == [2]
    assert result["text"].count("Python") == 2


def test_unreadable_photo_timeout_and_page_limit(monkeypatch):
    from PIL import Image
    output = BytesIO()
    image = Image.new("RGB", (300, 300), "white")
    image.save(output, format="PNG")
    image.close()
    with pytest.raises(ScreeningError, match="Insufficient"):
        extract_document(output.getvalue(), ".png")
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ocr", 120)
    monkeypatch.setattr("app.agents.ocr.subprocess.run", timeout)
    with pytest.raises(ScreeningError, match="120 seconds"):
        local_ocr(b"input", ".png")
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(31):
        writer.add_blank_page(width=100, height=100)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ScreeningError, match="30 pages"):
        extract_document(output.getvalue(), ".pdf")


def test_public_photo_is_stored_privately_as_pdf(api):
    from test_public_intake import setup_job
    from app.modules.recruiting.public_intake import pipeline_table
    from sqlalchemy import select
    client, app, _, headers = api
    url = setup_job(api)
    response = client.post(url, data={"name": "OCR Test", "email": "ocr@example.com",
        "phone": "9876543210", "consent": "on"}, files={"resume": ("resume.png", photo(), "image/png")})
    assert response.status_code == 200
    with app.state.sessions() as db:
        profile = db.execute(select(pipeline_table(db).c.object)).scalar_one()
    resume_url = next(item["value"] for item in profile if item["name"] == "resume")
    assert client.get(resume_url).status_code == 401
    saved = client.get(resume_url, headers=headers["recruiter"])
    assert saved.content.startswith(b"%PDF-")
    assert saved.headers["content-type"] == "application/pdf"
    bad = client.post(url, data={"name": "OCR Test", "email": "bad@example.com",
        "phone": "9876543210", "consent": "on"}, files={"resume": ("bad.png", b"not an image", "image/png")})
    assert bad.status_code == 422
