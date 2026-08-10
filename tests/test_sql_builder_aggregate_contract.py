from kernel.data_cognition.logical_plan import LogicalPlan, Projection
from kernel.data_cognition.sql_builder import SQLBuilder
from kernel.data_cognition.sql_dialect import detect_sql_dialect


def test_builder_applies_aggregate_function_from_projection_metadata():
    plan = LogicalPlan(
        tables=["orders o"],
        projections=[Projection(expr="o.amount", alias="revenue", agg_func="SUM")],
        group_by=["o.user_id"],
        limit=100,
    )

    sql = SQLBuilder().build(plan, detect_sql_dialect("mysql"))

    assert "SUM(o.amount) AS" in sql


def test_builder_compiles_count_star_from_aggregate_metadata():
    plan = LogicalPlan(
        tables=["orders"],
        projections=[Projection(expr="*", alias="count", agg_func="COUNT")],
        limit=100,
    )

    sql = SQLBuilder().build(plan, detect_sql_dialect("mysql"))

    assert "COUNT(*) AS" in sql
