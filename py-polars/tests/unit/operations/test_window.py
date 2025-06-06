from __future__ import annotations

import numpy as np
import pytest

import polars as pl
from polars.testing import assert_frame_equal, assert_series_equal


def test_over_args() -> None:
    df = pl.DataFrame(
        {
            "a": ["a", "a", "b"],
            "b": [1, 2, 3],
            "c": [3, 2, 1],
        }
    )

    # Single input
    expected = pl.Series("c", [3, 3, 1]).to_frame()
    result = df.select(pl.col("c").max().over("a"))
    assert_frame_equal(result, expected)

    # Multiple input as list
    expected = pl.Series("c", [3, 2, 1]).to_frame()
    result = df.select(pl.col("c").max().over(["a", "b"]))
    assert_frame_equal(result, expected)

    # Multiple input as positional args
    result = df.select(pl.col("c").max().over("a", "b"))
    assert_frame_equal(result, expected)


@pytest.mark.parametrize("dtype", [pl.Float32, pl.Float64, pl.Int32])
def test_std(dtype: type[pl.DataType]) -> None:
    if dtype == pl.Int32:
        df = pl.DataFrame(
            [
                pl.Series("groups", ["a", "a", "b", "b"]),
                pl.Series("values", [1, 2, 3, 4], dtype=dtype),
            ]
        )
    else:
        df = pl.DataFrame(
            [
                pl.Series("groups", ["a", "a", "b", "b"]),
                pl.Series("values", [1.0, 2.0, 3.0, 4.0], dtype=dtype),
            ]
        )

    out = df.select(pl.col("values").std().over("groups"))
    assert np.isclose(out["values"][0], 0.7071067690849304)

    out = df.select(pl.col("values").var().over("groups"))
    assert np.isclose(out["values"][0], 0.5)
    out = df.select(pl.col("values").mean().over("groups"))
    assert np.isclose(out["values"][0], 1.5)


def test_issue_2529() -> None:
    def stdize_out(value: str, control_for: str) -> pl.Expr:
        return (pl.col(value) - pl.mean(value).over(control_for)) / pl.std(value).over(
            control_for
        )

    df = pl.from_dicts(
        [
            {"cat": cat, "val1": cat + _, "val2": cat + _}
            for cat in range(2)
            for _ in range(2)
        ]
    )

    out = df.select(
        "*",
        stdize_out("val1", "cat").alias("out1"),
        stdize_out("val2", "cat").alias("out2"),
    )
    assert out["out1"].to_list() == out["out2"].to_list()


def test_window_function_cache() -> None:
    # ensures that the cache runs the flattened first (that are the sorted groups)
    # otherwise the flattened results are not ordered correctly
    out = pl.DataFrame(
        {
            "groups": ["A", "A", "B", "B", "B"],
            "groups_not_sorted": ["A", "B", "A", "B", "A"],
            "values": range(5),
        }
    ).with_columns(
        pl.col("values")
        .over("groups", mapping_strategy="join")
        .alias("values_list"),  # aggregation to list + join
        pl.col("values")
        .over("groups", mapping_strategy="explode")
        .alias("values_flat"),  # aggregation to list + explode and concat back
        pl.col("values")
        .reverse()
        .over("groups", mapping_strategy="explode")
        .alias("values_rev"),  # use flatten to reverse within a group
    )

    assert out["values_list"].to_list() == [
        [0, 1],
        [0, 1],
        [2, 3, 4],
        [2, 3, 4],
        [2, 3, 4],
    ]
    assert out["values_flat"].to_list() == [0, 1, 2, 3, 4]
    assert out["values_rev"].to_list() == [1, 0, 4, 3, 2]


def test_window_range_no_rows() -> None:
    df = pl.DataFrame({"x": [5, 5, 4, 4, 2, 2]})
    expr = pl.int_range(0, pl.len()).over("x")
    out = df.with_columns(int=expr)
    assert_frame_equal(
        out, pl.DataFrame({"x": [5, 5, 4, 4, 2, 2], "int": [0, 1, 0, 1, 0, 1]})
    )

    df = pl.DataFrame({"x": []}, schema={"x": pl.Float32})
    out = df.with_columns(int=expr)

    expected = pl.DataFrame(schema={"x": pl.Float32, "int": pl.Int64})
    assert_frame_equal(out, expected)


def test_no_panic_on_nan_3067() -> None:
    df = pl.DataFrame(
        {
            "group": ["a", "a", "a", "b", "b", "b"],
            "total": [1.0, 2, 3, 4, 5, np.nan],
        }
    )

    expected = [None, 1.0, 2.0, None, 4.0, 5.0]
    assert (
        df.select([pl.col("total").shift().over("group")])["total"].to_list()
        == expected
    )


def test_quantile_as_window() -> None:
    result = (
        pl.DataFrame(
            {
                "group": [0, 0, 1, 1],
                "value": [0, 1, 0, 2],
            }
        )
        .select(pl.quantile("value", 0.9).over("group"))
        .to_series()
    )
    expected = pl.Series("value", [1.0, 1.0, 2.0, 2.0])
    assert_series_equal(result, expected)


def test_cumulative_eval_window_functions() -> None:
    df = pl.DataFrame(
        {
            "group": [0, 0, 0, 1, 1, 1],
            "val": [20, 40, 30, 2, 4, 3],
        }
    )

    result = df.with_columns(
        pl.col("val")
        .cumulative_eval(pl.element().max())
        .over("group")
        .alias("cumulative_eval_max")
    )
    expected = pl.DataFrame(
        {
            "group": [0, 0, 0, 1, 1, 1],
            "val": [20, 40, 30, 2, 4, 3],
            "cumulative_eval_max": [20, 40, 40, 2, 4, 4],
        }
    )
    assert_frame_equal(result, expected)

    # 6394
    df = pl.DataFrame({"group": [1, 1, 2, 3], "value": [1, None, 3, None]})
    result = df.select(
        pl.col("value").cumulative_eval(pl.element().mean()).over("group")
    )
    expected = pl.DataFrame({"value": [1.0, 1.0, 3.0, None]})
    assert_frame_equal(result, expected)


def test_len_window() -> None:
    assert (
        pl.DataFrame(
            {
                "a": [1, 1, 2],
            }
        )
        .with_columns(pl.len().over("a"))["len"]
        .to_list()
    ) == [2, 2, 1]


def test_window_cached_keys_sorted_update_4183() -> None:
    df = pl.DataFrame(
        {
            "customer_ID": ["0", "0", "1"],
            "date": [1, 2, 3],
        }
    )
    result = df.sort(by=["customer_ID", "date"]).select(
        pl.count("date").over(pl.col("customer_ID")).alias("count"),
        pl.col("date").rank(method="ordinal").over(pl.col("customer_ID")).alias("rank"),
    )
    expected = pl.DataFrame(
        {"count": [2, 2, 1], "rank": [1, 2, 1]},
        schema={"count": pl.UInt32, "rank": pl.UInt32},
    )
    assert_frame_equal(result, expected)


def test_window_functions_list_types() -> None:
    df = pl.DataFrame(
        {
            "col_int": [1, 1, 2, 2],
            "col_list": [[1], [1], [2], [2]],
        }
    )
    assert (df.select(pl.col("col_list").shift(1).alias("list_shifted")))[
        "list_shifted"
    ].to_list() == [None, [1], [1], [2]]

    assert (df.select(pl.col("col_list").shift().alias("list_shifted")))[
        "list_shifted"
    ].to_list() == [None, [1], [1], [2]]

    assert (df.select(pl.col("col_list").shift(fill_value=[]).alias("list_shifted")))[
        "list_shifted"
    ].to_list() == [[], [1], [1], [2]]


def test_sorted_window_expression() -> None:
    size = 10
    df = pl.DataFrame(
        {"a": np.random.randint(10, size=size), "b": np.random.randint(10, size=size)}
    )
    expr = (pl.col("a") + pl.col("b")).over("b").alias("computed")

    out1 = df.with_columns(expr).sort("b")

    # explicit sort
    df = df.sort("b")
    out2 = df.with_columns(expr)

    assert_frame_equal(out1, out2)


def test_nested_aggregation_window_expression() -> None:
    df = pl.DataFrame(
        {
            "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 2, 13, 4, 15, 6, None, None, 19],
            "y": [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        }
    )

    result = df.with_columns(
        pl.when(pl.col("x") >= pl.col("x").quantile(0.1))
        .then(1)
        .otherwise(None)
        .over("y")
        .alias("foo")
    )
    expected = pl.DataFrame(
        {
            "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 2, 13, 4, 15, 6, None, None, 19],
            "y": [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1],
            "foo": [None, 1, 1, 1, 1, 1, 1, 1, 1, 1, None, 1, 1, 1, 1, None, None, 1],
        },
        # Resulting column is Int32, see https://github.com/pola-rs/polars/issues/8041
        schema_overrides={"foo": pl.Int32},
    )
    assert_frame_equal(result, expected)


def test_window_5868() -> None:
    df = pl.DataFrame({"value": [None, 2], "id": [None, 1]})

    result_df = df.with_columns(pl.col("value").max().over("id"))
    expected_df = pl.DataFrame({"value": [None, 2], "id": [None, 1]})
    assert_frame_equal(result_df, expected_df)

    df = pl.DataFrame({"a": [None, 1, 2, 3, 3, 3, 4, 4]})

    result = df.select(pl.col("a").sum().over("a")).get_column("a")
    expected = pl.Series("a", [0, 1, 2, 9, 9, 9, 8, 8])
    assert_series_equal(result, expected)

    result = (
        df.with_columns(pl.col("a").set_sorted())
        .select(pl.col("a").sum().over("a"))
        .get_column("a")
    )
    assert_series_equal(result, expected)

    result = df.drop_nulls().select(pl.col("a").sum().over("a")).get_column("a")
    expected = pl.Series("a", [1, 2, 9, 9, 9, 8, 8])
    assert_series_equal(result, expected)

    result = (
        df.drop_nulls()
        .with_columns(pl.col("a").set_sorted())
        .select(pl.col("a").sum().over("a"))
        .get_column("a")
    )
    assert_series_equal(result, expected)


def test_window_function_implode_contention_8536() -> None:
    df = pl.DataFrame(
        data={
            "policy": ["a", "b", "c", "c", "d", "d", "d", "d", "e", "e"],
            "memo": ["LE", "RM", "", "", "", "LE", "", "", "", "RM"],
        },
        schema={"policy": pl.String, "memo": pl.String},
    )

    assert df.select(
        (pl.lit("LE").is_in(pl.col("memo").over("policy", mapping_strategy="join")))
        | (pl.lit("RM").is_in(pl.col("memo").over("policy", mapping_strategy="join")))
    ).to_series().to_list() == [
        True,
        True,
        False,
        False,
        True,
        True,
        True,
        True,
        True,
        True,
    ]


def test_cached_windows_sync_8803() -> None:
    assert (
        pl.DataFrame(
            [
                pl.Series("id", [4, 5, 4, 6, 4, 5], dtype=pl.Int64),
                pl.Series(
                    "is_valid",
                    [True, False, False, False, False, False],
                    dtype=pl.Boolean,
                ),
            ]
        )
        .with_columns(
            a=pl.lit(True).is_in(pl.col("is_valid")).over("id"),
            b=pl.col("is_valid").sum().gt(0).over("id"),
        )
        .sum()
    ).to_dict(as_series=False) == {"id": [28], "is_valid": [1], "a": [3], "b": [3]}


def test_window_filtered_aggregation() -> None:
    df = pl.DataFrame(
        {
            "group": ["A", "A", "B", "B"],
            "field1": [2, 4, 6, 8],
            "flag": [1, 0, 1, 1],
        }
    )
    out = df.with_columns(
        pl.col("field1").filter(pl.col("flag") == 1).mean().over("group").alias("mean")
    )
    expected = pl.DataFrame(
        {
            "group": ["A", "A", "B", "B"],
            "field1": [2, 4, 6, 8],
            "flag": [1, 0, 1, 1],
            "mean": [2.0, 2.0, 7.0, 7.0],
        }
    )
    assert_frame_equal(out, expected)


def test_window_filtered_false_15483() -> None:
    df = pl.DataFrame(
        {
            "group": ["A", "A"],
            "value": [1, 2],
        }
    )
    out = df.with_columns(
        pl.col("value").filter(pl.col("group") != "A").arg_max().over("group")
    )
    expected = pl.DataFrame(
        {
            "group": ["A", "A"],
            "value": [None, None],
        },
        schema_overrides={"value": pl.UInt32},
    )
    assert_frame_equal(out, expected)


def test_window_and_cse_10152() -> None:
    q = pl.LazyFrame(
        {
            "a": [0.0],
            "b": [0.0],
        }
    )

    q = q.with_columns(
        a=pl.col("a").diff().over("a") / pl.col("a"),
        b=pl.col("b").diff().over("a") / pl.col("a"),
        c=pl.col("a").diff().over("a"),
    )

    assert q.collect().columns == ["a", "b", "c"]


def test_window_10417() -> None:
    df = pl.DataFrame({"a": [1], "b": [1.2], "c": [2.1]})

    assert df.lazy().with_columns(
        pl.col("b") - pl.col("b").mean().over("a"),
        pl.col("c") - pl.col("c").mean().over("a"),
    ).collect().to_dict(as_series=False) == {"a": [1], "b": [0.0], "c": [0.0]}


def test_window_13173() -> None:
    df = pl.DataFrame(
        data={
            "color": ["yellow", "yellow"],
            "color2": [None, "light"],
            "val": ["2", "3"],
        }
    )
    assert df.with_columns(
        pl.min("val").over(["color", "color2"]).alias("min_val_per_color")
    ).to_dict(as_series=False) == {
        "color": ["yellow", "yellow"],
        "color2": [None, "light"],
        "val": ["2", "3"],
        "min_val_per_color": ["2", "3"],
    }


def test_window_agg_list_null_15437() -> None:
    df = pl.DataFrame({"a": [None]})
    output = df.select(pl.concat_list("a").over(1))
    expected = pl.DataFrame({"a": [[None]]})
    assert_frame_equal(output, expected)


@pytest.mark.release
def test_windows_not_cached() -> None:
    ldf = (
        pl.DataFrame(
            [
                pl.Series("key", ["a", "a", "b", "b"]),
                pl.Series("val", [2, 2, 1, 3]),
            ]
        )
        .lazy()
        .filter(
            (pl.col("key").cum_count().over("key") == 1)
            | (pl.col("val").shift(1).over("key").is_not_null())
            | (pl.col("val") != pl.col("val").shift(1).over("key"))
        )
    )
    # this might fail if they are cached
    for _ in range(1000):
        ldf.collect()


def test_window_order_by_8662() -> None:
    df = pl.DataFrame(
        {
            "g": [1, 1, 1, 1, 2, 2, 2, 2],
            "t": [1, 2, 3, 4, 4, 1, 2, 3],
            "x": [10, 20, 30, 40, 10, 20, 30, 40],
        }
    )

    assert df.with_columns(
        x_lag0=pl.col("x").shift(1).over("g"),
        x_lag1=pl.col("x").shift(1).over("g", order_by="t"),
        x_lag2=pl.col("x").shift(1).over("g", order_by="t", descending=True),
    ).to_dict(as_series=False) == {
        "g": [1, 1, 1, 1, 2, 2, 2, 2],
        "t": [1, 2, 3, 4, 4, 1, 2, 3],
        "x": [10, 20, 30, 40, 10, 20, 30, 40],
        "x_lag0": [None, 10, 20, 30, None, 10, 20, 30],
        "x_lag1": [None, 10, 20, 30, 40, None, 20, 30],
        "x_lag2": [20, 30, 40, None, None, 30, 40, 10],
    }


def test_window_chunked_std_17102() -> None:
    c1 = pl.DataFrame({"A": [1, 1], "B": [1.0, 2.0]})
    c2 = pl.DataFrame({"A": [2, 2], "B": [1.0, 2.0]})

    df = pl.concat([c1, c2], rechunk=False)
    out = df.select(pl.col("B").std().over("A").alias("std"))
    assert out.unique().item() == 0.7071067811865476


def test_window_17308() -> None:
    df = pl.DataFrame({"A": [1, 2], "B": [3, 4], "grp": ["A", "B"]})

    assert df.select(pl.col("A").sum(), pl.col("B").sum().over("grp")).to_dict(
        as_series=False
    ) == {"A": [3, 3], "B": [3, 4]}


def test_lit_window_broadcast() -> None:
    # the broadcast should happen in the window function
    assert pl.DataFrame({"a": [1, 1, 2]}).select(pl.lit(0).over("a").alias("a"))[
        "a"
    ].to_list() == [0, 0, 0]


def test_order_by_sorted_keys_18943() -> None:
    df = pl.DataFrame(
        {
            "g": [1, 1, 1, 1],
            "t": [4, 3, 2, 1],
            "x": [10, 20, 30, 40],
        }
    )

    expect = pl.DataFrame({"x": [100, 90, 70, 40]})

    out = df.select(pl.col("x").cum_sum().over("g", order_by="t"))
    assert_frame_equal(out, expect)

    out = df.set_sorted("g").select(pl.col("x").cum_sum().over("g", order_by="t"))
    assert_frame_equal(out, expect)


def test_nested_window_keys() -> None:
    df = pl.DataFrame({"x": 1, "y": "two"})
    assert df.select(pl.col("y").first().over(pl.struct("x").implode())).item() == "two"
    assert df.select(pl.col("y").first().over(pl.struct("x"))).item() == "two"


def test_window_21692() -> None:
    df = pl.DataFrame(
        {
            "a": [1, 2, 3, 1, 2, 3],
            "b": [4, 3, 0, 1, 2, 0],
            "c": ["first", "first", "first", "second", "second", "second"],
        }
    )
    gt0 = pl.col("b") > 0
    assert df.with_columns(
        corr=pl.corr(
            pl.col("a").filter(gt0),
            pl.col("b").filter(gt0),
        ).over("c"),
    ).to_dict(as_series=False) == {
        "a": [1, 2, 3, 1, 2, 3],
        "b": [4, 3, 0, 1, 2, 0],
        "c": ["first", "first", "first", "second", "second", "second"],
        "corr": [-1.0, -1.0, -1.0, 1.0, 1.0, 1.0],
    }


def test_window_implode_explode() -> None:
    assert pl.DataFrame(
        {
            "x": [1, 2, 3, 1, 2, 3, 1, 2, 3],
            "y": [2, 2, 2, 3, 3, 3, 4, 4, 4],
        }
    ).select(
        works=(pl.col.x * pl.col.x.implode().explode()).over(pl.col.y),
    ).to_dict(as_series=False) == {"works": [1, 4, 9, 1, 4, 9, 1, 4, 9]}


def test_window_22006() -> None:
    df = pl.DataFrame(
        [
            {"a": 1, "b": 1},
            {"a": 1, "b": 2},
            {"a": 2, "b": 3},
            {"a": 2, "b": 4},
        ]
    )

    df_empty = pl.DataFrame([], df.schema)

    df_out = df.select(c=pl.col("b").over("a", mapping_strategy="join"))

    df_empty_out = df_empty.select(c=pl.col("b").over("a", mapping_strategy="join"))

    assert df_out.schema == df_empty_out.schema


def test_when_then_over_22478() -> None:
    q = pl.LazyFrame(
        {
            "x": [True, True, False, True, True, True, False],
            "t": [1, 2, 3, 4, 5, 6, 7],
        }
    ).with_columns(
        duration=(
            pl.when(pl.col("x"))
            .then(pl.col("t").last() - pl.col("t").first())
            .otherwise(pl.lit(0))
            .over(pl.col("x").rle_id())
        )
    )

    expect = pl.DataFrame(
        {
            "x": [True, True, False, True, True, True, False],
            "t": [1, 2, 3, 4, 5, 6, 7],
            "duration": [1, 1, 0, 2, 2, 2, 0],
        }
    )

    assert q.collect_schema() == {
        "x": pl.Boolean,
        "t": pl.Int64,
        "duration": pl.Int64,
    }
    assert_frame_equal(q.collect(), expect)

    q = pl.LazyFrame({"key": [1, 1, 2, 2, 2]}).with_columns(
        out=pl.when(pl.Series(99 * [True])).then(pl.sum("key")).over("key")
    )

    with pytest.raises(
        pl.exceptions.ComputeError,
        match="the length of the window expression did not match that of the group",
    ):
        q.collect()


def test_window_fold_22493() -> None:
    df = pl.DataFrame({"a": [1, 1, 1, 2, 2, 2, 2, 2], "b": [1, 1, 1, 2, 2, 2, 2, 2]})

    assert (
        df.select(
            (
                pl.when(False)
                .then(1)
                .otherwise(
                    pl.fold(
                        acc=pl.lit(0.0),
                        function=lambda acc, x: acc + x,
                        exprs=pl.col(["a", "b"]),
                        returns_scalar=False,
                    )
                )
            )
            .over("a")
            .alias("prod"),
        )
    ).to_dict(as_series=False) == {"prod": [2.0, 2.0, 2.0, 4.0, 4.0, 4.0, 4.0, 4.0]}

    assert (
        df.select(
            (
                pl.when(False)
                .then(1)
                .otherwise(
                    pl.fold(
                        acc=pl.lit(0.0),
                        function=lambda acc, x: acc + x.sum(),
                        exprs=pl.col(["a", "b"]),
                        returns_scalar=True,
                    )
                )
            )
            .over("a")
            .alias("prod"),
        )
    ).to_dict(as_series=False) == {
        "prod": [6.0, 6.0, 6.0, 20.0, 20.0, 20.0, 20.0, 20.0]
    }

    with pytest.raises(pl.exceptions.InvalidOperationError):
        (
            df.select(
                (
                    pl.when(False)
                    .then(1)
                    .otherwise(
                        pl.fold(
                            acc=pl.lit(0.0),
                            function=lambda acc, x: acc + x,
                            exprs=pl.col(["a", "b"]),
                            returns_scalar=True,
                        )
                    )
                )
                .over("a")
                .alias("prod"),
            )
        )
