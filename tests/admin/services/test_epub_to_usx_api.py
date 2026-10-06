"""The real CUSX worker runs through the existing fire-and-poll HTTP flow."""

import io
import zipfile

from admin.services.jobs import result_filename_for


def epub_bytes(body="<h1>Chapter 1</h1><p>Hello <b>world</b>.</p>"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "book.opf",
            '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>API Book</dc:title></metadata><manifest><item id="one" href="one.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>',
        )
        archive.writestr("one.xhtml", "<html><body>" + body + "</body></html>")
    return buffer.getvalue()


def test_cusx_job_poll_download_and_owner_scope(client, manager, claims_holder, tmp_path):
    claims_holder["claims"] = {"sub": "alice"}
    response = client.post("/convert/epub-to-usx", files={"file": ("book.epub", epub_bytes())})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    queued = client.get(f"/convert/{job_id}").json()
    assert queued["result_filename"].endswith(".cusx")
    assert not queued["download_ready"]
    assert client.get(f"/convert/{job_id}/download").status_code == 409
    manager._executor.run_all()
    status = client.get(f"/convert/{job_id}").json()
    assert status["status"] == "succeeded", status
    assert status["validation"]["valid"]
    assert status["result_filename"].endswith(".cusx")
    download = client.get(f"/convert/{job_id}/download")
    assert download.status_code == 200
    assert ".cusx" in download.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert "metadata.xml" in archive.namelist()
        assert "release/USX_1/chapter-i.usx" in archive.namelist()
        assert not any(n.endswith(".sqlite") for n in archive.namelist())
    assert list((tmp_path / "results").glob("*.conversion-metadata.sqlite"))
    assert not list((tmp_path / "work").iterdir())
    assert client.get(f"/convert/{job_id}/manifest").status_code == 409
    claims_holder["claims"] = {"sub": "mallory"}
    assert client.get(f"/convert/{job_id}/download").status_code == 404


def test_generic_route_can_select_cusx_and_reject_other_formats(client, manager):
    response = client.post(
        "/convert",
        files={"file": ("book.epub", epub_bytes())},
        data={"source_format": "epub", "name": "Book", "output_format": "cusx"},
    )
    assert response.status_code == 202
    manager._executor.run_all()
    assert client.get(response.json()["status_url"]).json()["status"] == "succeeded"
    response = client.post(
        "/convert",
        files={"file": ("plain.txt", b"Text")},
        data={"source_format": "plain", "name": "Book", "output_format": "cusx"},
    )
    assert response.status_code == 422


def test_unsupported_content_fails_job_without_download_and_cleans_scratch(
    client, manager, tmp_path
):
    response = client.post(
        "/convert/epub-to-usx",
        files={"file": ("book.epub", epub_bytes('<p><a href="#absent">Broken</a></p>'))},
    )
    assert response.status_code == 202
    manager._executor.run_all()
    status = client.get(response.json()["status_url"]).json()
    assert status["status"] == "failed"
    assert "missing content anchor" in status["error"]
    assert not status["download_ready"]
    assert not list((tmp_path / "work").iterdir())
    assert not list((tmp_path / "results").glob("*.cusx"))


def test_cusx_queued_filename_contract():
    assert result_filename_for("A Book", "epub-to-usx") == "a-book.cusx"
