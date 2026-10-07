"""`scripts/load_products.py`: carga el catálogo en la base de Render desde la
máquina local con `import_catalog`.

El script no es un paquete importable, así que se carga por ruta con
`importlib`. `main` recibe el entorno como dict para que los tests no toquen
`os.environ`; Django ya está configurado por pytest-django, así que la
conexión real sigue siendo la base de test aunque el script fije `POSTGRES_*`
en ese dict. Sin proveedores que mockear.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from apps.catalog.models import Product

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load_products.py"
RENDER_URL = "postgresql://torque_user:p%40ss@dpg-abc123-a.virginia-postgres.render.com/torque_db"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("load_products", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env_file(tmp_path, content):
    path = tmp_path / ".env.render"
    path.write_text(content, encoding="utf-8")
    return path


def _products_file(tmp_path, products):
    path = tmp_path / "products.json"
    path.write_text(json.dumps(products), encoding="utf-8")
    return path


# --- database_env ----------------------------------------------------------


def test_database_env_maps_render_url_to_postgres_variables(script):
    assert script.database_env(RENDER_URL) == {
        "POSTGRES_DB": "torque_db",
        "POSTGRES_USER": "torque_user",
        "POSTGRES_PASSWORD": "p@ss",
        "POSTGRES_HOST": "dpg-abc123-a.virginia-postgres.render.com",
        "POSTGRES_PORT": "5432",
        "DATABASE_SSL": "true",
    }


def test_database_env_keeps_an_explicit_port_and_accepts_postgres_scheme(script):
    env = script.database_env("postgres://u:p@db.example.com:6543/catalog?sslmode=require")

    assert env["POSTGRES_PORT"] == "6543"
    assert env["POSTGRES_DB"] == "catalog"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "mysql://u:p@db.example.com/catalog",
        "postgresql://u:p@/catalog",
        "postgresql://u:p@db.example.com/",
        "postgresql://db.example.com/catalog",
    ],
)
def test_database_env_rejects_incomplete_urls(script, url):
    with pytest.raises(ValueError):
        script.database_env(url)


# --- read_env_file ---------------------------------------------------------


def test_read_env_file_skips_comments_and_strips_quotes(script, tmp_path):
    path = _env_file(
        tmp_path,
        "# Render > Connections > External Database URL\n\nDATABASE_URL=\"postgresql://a\"\n"
        "OTHER='x=y'\n",
    )

    assert script.read_env_file(path) == {"DATABASE_URL": "postgresql://a", "OTHER": "x=y"}


# --- main --------------------------------------------------------------------


def test_main_fails_without_a_database_url(script, tmp_path, capsys):
    products = _products_file(tmp_path, [{"id": "a", "price": 10}])

    code = script.main(
        [str(products), "--env-file", str(tmp_path / "missing.env"), "--dry-run"], environ={}
    )

    assert code == 2
    assert "DATABASE_URL" in capsys.readouterr().err


@pytest.mark.django_db
def test_main_dry_run_lists_unpriced_products_and_writes_nothing(script, tmp_path, capsys):
    products = _products_file(
        tmp_path, [{"id": "needs-price", "price": 0}, {"id": "priced", "price": 5}]
    )
    env_file = _env_file(tmp_path, f"DATABASE_URL={RENDER_URL}\n")
    environ = {}

    code = script.main([str(products), "--env-file", str(env_file), "--dry-run"], environ=environ)

    assert code == 1
    captured = capsys.readouterr()
    assert "needs-price" in captured.err
    assert "dpg-abc123-a.virginia-postgres.render.com" in captured.out
    assert "p@ss" not in captured.out + captured.err
    assert environ["POSTGRES_HOST"] == "dpg-abc123-a.virginia-postgres.render.com"
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_main_dry_run_passes_for_a_priced_catalog(script, tmp_path, capsys):
    products = _products_file(tmp_path, [{"id": "priced", "price": 5}])
    env_file = _env_file(tmp_path, f"DATABASE_URL={RENDER_URL}\n")

    code = script.main([str(products), "--env-file", str(env_file), "--dry-run"], environ={})

    assert code == 0
    assert "Dry run: nothing was written." in capsys.readouterr().out
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_main_aborts_when_the_write_is_not_confirmed(script, tmp_path, monkeypatch, capsys):
    products = _products_file(tmp_path, [{"id": "priced", "price": 5}])
    env_file = _env_file(tmp_path, f"DATABASE_URL={RENDER_URL}\n")
    monkeypatch.setattr("builtins.input", lambda prompt: "no")

    code = script.main([str(products), "--env-file", str(env_file)], environ={})

    assert code == 1
    assert not Product.objects.exists()


@pytest.mark.django_db
def test_main_imports_after_confirmation(script, tmp_path):
    products = _products_file(tmp_path, [{"id": "priced", "price": 5}])
    env_file = _env_file(tmp_path, f"DATABASE_URL={RENDER_URL}\n")

    code = script.main([str(products), "--env-file", str(env_file), "--yes"], environ={})

    assert code == 0
    assert Product.objects.get(pk="priced").data == {"id": "priced", "price": 5}
