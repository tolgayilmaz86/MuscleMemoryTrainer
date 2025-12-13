from mmt_app.app import resource_path


def test_resource_path_points_to_existing_theme() -> None:
    theme = resource_path("styles", "theme.qss")
    assert theme.exists()
