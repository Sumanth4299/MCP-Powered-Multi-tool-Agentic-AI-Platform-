from backend.api.conversations import _extract_text


def test_extract_text_returns_string_content_unchanged() -> None:
    assert _extract_text(" assistant reply ") == " assistant reply "


def test_extract_text_joins_list_of_text_blocks() -> None:
    assert _extract_text([{"text": "Hello"}, {"text": " world"}]) == "Hello world"


def test_extract_text_handles_object_blocks_and_other_values() -> None:
    class TextBlock:
        text = "Hello"

    assert _extract_text([TextBlock(), "!"]) == "Hello!"
