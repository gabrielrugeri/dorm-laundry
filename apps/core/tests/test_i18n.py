import pytest
from django.urls import reverse


@pytest.mark.parametrize(
    ("language", "expected"),
    [("ru", "Забронировать стиральную машину"), ("en", "Book a washing machine")],
)
def test_home_renders_in_both_languages(client, resident, language, expected):
    client.force_login(resident.user)
    client.cookies["django_language"] = language
    response = client.get(reverse("core:home"))
    assert response.status_code == 200
    assert expected in response.content.decode()


def test_default_language_is_russian(client):
    response = client.get(reverse("accounts:login"))
    assert '<html lang="ru">' in response.content.decode()


def test_language_switch_sets_cookie(client):
    response = client.post(reverse("set_language"), {"language": "en", "next": "/"})
    assert response.status_code == 302
    assert response.cookies["django_language"].value == "en"
