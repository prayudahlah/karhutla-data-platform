"""Machine learning untuk klasifikasi kebakaran per sel 0,25°.

Alur: Gold ``hotspot_cell_day`` -> dataset biner -> training -> inference ->
Postgres. Agregasi sel dan label dikerjakan dbt, bukan Python, supaya training
dan inference memakai angka yang sama.
"""
