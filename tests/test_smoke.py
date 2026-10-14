from django.conf import settings


def test_settings_load():
    assert settings.LANGUAGE_CODE == "ru"
    assert settings.USE_TZ is True


def test_admin_login_page_renders(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
