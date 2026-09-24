from apps.common.links import DEFAULT_APP_URL, app_url


def test_app_url_joins_the_path_without_a_double_slash(settings):
    settings.APP_URL = "https://shop.example.com/"

    assert app_url("/activate?token=t") == "https://shop.example.com/activate?token=t"


def test_app_url_falls_back_to_the_dev_spa_when_the_setting_is_empty(settings):
    settings.APP_URL = ""

    assert app_url("/quote/abc") == f"{DEFAULT_APP_URL}/quote/abc"
