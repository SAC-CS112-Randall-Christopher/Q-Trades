"""Owned, finite PDF text extraction. No network, OCR, writes or model dependencies."""

import base64
import io
import json
import os
import sys


def main() -> None:
    if os.name != "nt":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))  # type: ignore[attr-defined]
    from pypdf import PdfReader, __version__

    command = json.loads(sys.stdin.buffer.read(200000))
    raw = base64.b64decode(command["bytes"], validate=True)
    if len(raw) > 131072:
        raise ValueError("Bounded PDF input required")
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= command["first"] <= command["last"] <= len(reader.pages):
        raise ValueError("Encrypted PDF or unavailable page range")
    if command["last"] - command["first"] >= 6:
        raise ValueError("At most six PDF pages")
    pages = []
    for index in range(command["first"] - 1, command["last"]):
        text = reader.pages[index].extract_text()
        if not text or not text.strip() or "\ufffd" in text:
            raise ValueError("Scanned/garbled PDF needs separate permitted OCR")
        pages.append(f"[PDF page {index + 1}]\n{text}")
        if len("\n\n".join(pages).encode()) > 65536:
            raise ValueError("Choose a smaller complete section")
    print(
        json.dumps(
            {
                "text": "\n\n".join(pages),
                "extraction": {
                    "method": "pypdf-native-v1",
                    "version": __version__,
                    "first_page": command["first"],
                    "last_page": command["last"],
                    "document_pages": len(reader.pages),
                    "ocr": False,
                },
            }
        )
    )


if __name__ == "__main__":
    main()
