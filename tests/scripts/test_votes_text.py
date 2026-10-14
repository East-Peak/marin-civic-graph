"""Votes Part A: the canonical text every later stage indexes (spans are offsets into it)."""
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_text import CanonicalText, canonical_text, html_lines, docx_lines, pdf_lines  # noqa: E402


class TestHtml:
    def test_a_table_row_is_one_line_with_cells_joined(self):
        html = ("<table><tr><td><div>AYES:</div></td><td><div><span>\n\t Supervisor  Alder, \n"
                "\t\tSupervisor Birch</span></div></td></tr></table>")
        assert html_lines(html) == ["AYES: Supervisor Alder, Supervisor Birch"]

    def test_block_tags_break_lines_outside_rows_and_empty_lines_drop(self):
        html = "<p>Roll Call</p><div>Present:<br/>Supervisor Alder;</div><p> </p><blockquote>1.</blockquote>"
        assert html_lines(html) == ["Roll Call", "Present:", "Supervisor Alder;", "1."]

    def test_script_style_and_title_content_never_reach_the_text(self):
        html = ("<html><head><title>T</title><style>body{x}</style></head><script>var a=1;</script>"
                "<body><p>Kept</p></body></html>")
        assert html_lines(html) == ["Kept"]

    def test_entities_and_nbsp_are_resolved(self):
        assert html_lines("<p>Motion&#160;carried 4-0&nbsp;Abstain:1 &amp; more</p>") == [
            "Motion carried 4-0 Abstain:1 & more"]

    def test_nested_table_inside_a_row_stays_on_the_row(self):
        html = ("<table><tr><td>CA-11.</td><td><p>Sheriff<br/>Request to apply.</p></td></tr>"
                "<tr><td>Vote:</td><td>Motion carried</td></tr></table>")
        assert html_lines(html) == ["CA-11. Sheriff Request to apply.", "Vote: Motion carried"]


def _docx(paragraphs_xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{paragraphs_xml}</w:body></w:document>")
    return buf.getvalue()


class TestDocx:
    def test_paragraphs_runs_tabs_and_breaks(self):
        data = _docx("<w:p><w:r><w:t>AYES:</w:t></w:r><w:r><w:tab/><w:t>ALDER, </w:t></w:r>"
                     "<w:r><w:t>BIRCH</w:t></w:r></w:p><w:p/><w:p><w:r><w:t>NOES:</w:t><w:br/>"
                     "<w:t xml:space=\"preserve\"> None</w:t></w:r></w:p>")
        assert docx_lines(data) == ["AYES: ALDER, BIRCH", "", "NOES:", " None"]

    def test_a_table_row_is_one_line(self):
        data = _docx("<w:tbl><w:tr><w:tc><w:p><w:r><w:t>AYES:</w:t></w:r></w:p></w:tc>"
                     "<w:tc><w:p><w:r><w:t>ALDER</w:t></w:r></w:p></w:tc></w:tr></w:tbl>")
        assert docx_lines(data) == ["AYES: ALDER"]


class TestPdf:
    def test_form_feed_is_its_own_line_and_lines_are_rstripped(self):
        assert pdf_lines("A.  ROLL CALL   \n  AYES:  ALDER\n\fNOES: None\n") == [
            "A.  ROLL CALL", "  AYES:  ALDER", "\f", "NOES: None"]


class TestCanonical:
    def test_quotes_and_dashes_fold_to_ascii(self):
        ct = CanonicalText.from_lines(["O’ALDER “quoted” – x"])
        assert ct.text == "O'ALDER \"quoted\" - x"

    def test_line_locator(self):
        ct = CanonicalText.from_lines(["first", "second line", "third"])
        start = ct.text.index("line")
        loc = ct.locate(start, start + 4)
        assert (loc["line_start"], loc["line_end"]) == (2, 2)
        assert ct.text[loc["start"]:loc["end"]] == "line"
        loc = ct.locate(0, ct.text.index("third") + 5)
        assert (loc["line_start"], loc["line_end"]) == (1, 3)

    def test_text_sha_pins_the_canonicalizer(self):
        ct = CanonicalText.from_lines(["a", "b"])
        assert ct.sha256 == hashlib.sha256("a\nb".encode()).hexdigest()

    def test_dispatch_by_format(self, tmp_path):
        p = tmp_path / "m.html"
        p.write_bytes(b"<p>One</p><p>Two</p>")
        assert canonical_text(p, "html").text == "One\nTwo"
        with pytest.raises(ValueError):
            canonical_text(p, "rtf")
