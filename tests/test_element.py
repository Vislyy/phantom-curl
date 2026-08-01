import pytest

from phantom_curl.exceptions import StaleElementError


def test_element_reads_content_attributes_and_selector_metadata(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/elements/")
    input_element = page.query_selector("#name")

    assert input_element is not None
    assert input_element.selector == "#name"
    assert input_element.created_url == f"{http_server}/elements/"
    assert input_element.get_attribute("data-kind") == "name"
    assert input_element.get_attribute("missing") is None
    assert input_element.attrs == {"id": "name", "class": "field", "data-kind": "name"}
    assert 'id="name"' in input_element.html
    assert input_element.inner_html == ""


def test_element_type_dispatches_input_events(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/elements/")
    input_element = page.query_selector("#name")

    assert input_element is not None
    input_element.type("Ada")

    assert page.evaluate("document.getElementById('name').value") == "Ada"
    assert page.body is not None
    assert page.body.get_attribute("input-value") == "Ada"


def test_element_click_and_custom_event_reach_dom_listeners(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/elements/")
    button = page.query_selector("#action")

    assert button is not None
    button.click()
    assert page.body is not None
    assert page.body.get_attribute("clicked") == "yes"

    assert button.dispatch_event("custom-event") is True
    assert page.body.get_attribute("custom-event") == "yes"


def test_query_selector_all_returns_elements_in_document_order(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/elements/")

    assert [element.text for element in page.query_selector_all(".item")] == ["First", "Second"]


def test_element_becomes_stale_after_navigation(phantom_client, http_server: str) -> None:
    page = phantom_client.new_page(f"{http_server}/elements/")
    element = page.query_selector("#name")

    assert element is not None
    page.goto(f"{http_server}/elements/")

    with pytest.raises(StaleElementError, match="no longer attached") as error:
        _ = element.attrs

    assert error.value.selector == "#name"
    assert error.value.created_url == f"{http_server}/elements/"
    assert error.value.current_url == f"{http_server}/elements/"
