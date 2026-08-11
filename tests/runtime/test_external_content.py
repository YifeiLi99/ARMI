from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from armi_kernel.application import (
    ExternalContentRecognitionRequest,
    ExternalMessagePartKind,
    ExternalMessageViolation,
)
from armi_kernel.contracts import TraceId
from armi_runtime.adapters.model.external_content import (
    _input_message,
    load_external_recognition_binding,
)
from armi_runtime.composition.external_content_extractors import (
    extract_external_content,
)
from docx import Document
from openpyxl import Workbook
from pptx import Presentation


class ExternalContentExtractorTests(unittest.TestCase):
    def test_extracts_text_json_csv_and_gb18030(self) -> None:
        text = extract_external_content(
            kind=ExternalMessagePartKind.FILE,
            content="中文".encode("gb18030"),
            file_name="note.txt",
        )
        document = extract_external_content(
            kind=ExternalMessagePartKind.FILE,
            content=b'{"answer": 42}',
            file_name="value.json",
        )
        table = extract_external_content(
            kind=ExternalMessagePartKind.FILE,
            content=b"a,b\n1,2\n",
            file_name="value.csv",
        )
        self.assertEqual(text.text, "中文")
        self.assertIn('"answer": 42', document.text or "")
        self.assertEqual(table.text, "a | b\n1 | 2")

    def test_detects_office_container_independently_of_extension(self) -> None:
        docx_value = io.BytesIO()
        document = Document()
        document.add_paragraph("正文")
        document.save(docx_value)
        pptx_value = io.BytesIO()
        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[0])
        slide.shapes.title.text = "标题"
        presentation.save(pptx_value)
        xlsx_value = io.BytesIO()
        workbook = Workbook()
        workbook.active.title = "数据"
        workbook.active.append(("字段", "值"))
        workbook.save(xlsx_value)
        workbook.close()

        extracted = (
            extract_external_content(
                kind=ExternalMessagePartKind.FILE,
                content=value,
                file_name="opaque.bin",
            )
            for value in (
                docx_value.getvalue(),
                pptx_value.getvalue(),
                xlsx_value.getvalue(),
            )
        )
        docx, pptx, xlsx = extracted
        self.assertEqual(docx.text, "正文")
        self.assertIn("wordprocessingml", docx.media_type)
        self.assertIn("[幻灯片 1]\n标题", pptx.text or "")
        self.assertIn("[工作表 数据]\n字段 | 值", xlsx.text or "")

    def test_routes_pdf_and_rejects_mismatched_media(self) -> None:
        pdf = extract_external_content(
            kind=ExternalMessagePartKind.FILE,
            content=b"%PDF-1.7\nprobe",
            file_name="document.bin",
        )
        self.assertTrue(pdf.requires_provider)
        self.assertEqual(pdf.media_type, "application/pdf")
        with self.assertRaisesRegex(
            ExternalMessageViolation, "EXTERNAL-MESSAGE-MEDIA-TYPE"
        ):
            extract_external_content(
                kind=ExternalMessagePartKind.IMAGE,
                content=b"not-an-image",
                file_name="image.png",
            )


class ExternalContentModelRequestTests(unittest.TestCase):
    def test_loads_packaged_recognition_models(self) -> None:
        binding = load_external_recognition_binding(
            Path(
                "apps/armi-runtime/src/armi_runtime/composition/"
                "runtime_resources/model-bindings.manifest.json"
            )
        )
        self.assertEqual(
            binding.model_for(ExternalMessagePartKind.IMAGE),
            "doubao-seed-evolving",
        )
        self.assertEqual(
            binding.model_for(ExternalMessagePartKind.AUDIO),
            "doubao-seed-2-0-lite-260428",
        )

    def test_builds_base64_requests_for_each_provider_media_kind(self) -> None:
        expected_types = {
            ExternalMessagePartKind.IMAGE: "input_image",
            ExternalMessagePartKind.AUDIO: "input_audio",
            ExternalMessagePartKind.VIDEO: "input_video",
            ExternalMessagePartKind.FILE: "input_file",
        }
        for kind, expected in expected_types.items():
            with self.subTest(kind=kind):
                value = _input_message(
                    ExternalContentRecognitionRequest(
                        kind,
                        b"sample",
                        "sample.bin",
                        "application/octet-stream",
                        TraceId("1" * 32),
                    )
                )
                self.assertEqual(value["content"][1]["type"], expected)
                self.assertNotIn("file_id", json.dumps(value))


if __name__ == "__main__":
    unittest.main()
