"""Helpers sin estado que comparten las apps de dominio.

No es una app de Django: no tiene modelos, views, urls ni migraciones, y no
importa ninguna app de dominio, así cualquiera puede usarla sin crear ciclos.
`backend/tests/test_app_boundaries.py` lo verifica.
"""
