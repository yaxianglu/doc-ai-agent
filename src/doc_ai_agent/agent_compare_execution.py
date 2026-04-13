from __future__ import annotations

from .agent_comparison import comparison_conclusion, comparison_domain_label, comparison_summary, window_summary


def execute_compare_request(
    *,
    question: str,
    compare_request: dict,
    route_seed: dict,
    query_engine,
    infer_region_level_from_name,
) -> dict:
    if compare_request["kind"] == "region_compare":
        domain = str(compare_request["domain"])
        domain_label = comparison_domain_label(domain)
        regions = list(compare_request["regions"])
        base_query_type = str(compare_request["base_query_type"])
        summaries: list[dict] = []
        subqueries: list[dict] = []
        for region in regions:
            route = dict(route_seed)
            route.update(
                {
                    "query_type": base_query_type,
                    "city": region,
                    "county": None,
                    "region_level": "city",
                }
            )
            result = query_engine.answer(question, plan=route)
            summaries.append(comparison_summary(domain, region, list(result.data or [])))
            subqueries.append(
                {
                    "region_name": region,
                    "query_type": base_query_type,
                    "since": route.get("since"),
                    "until": route.get("until"),
                }
            )
        title = "变化对比" if base_query_type.endswith("_trend") else "对比结果"
        left, right = summaries[0], summaries[1]
        answer = "\n".join(
            [
                f"{window_summary(route_seed.get('window'))}{domain_label}{title}：",
                f"- {left['region_name']}：趋势{left['trend']}，均值{left['average']:.1f}，峰值{left['peak']:.1f}，最近值{left['latest']:.1f}",
                f"- {right['region_name']}：趋势{right['trend']}，均值{right['average']:.1f}，峰值{right['peak']:.1f}，最近值{right['latest']:.1f}",
                comparison_conclusion(left, right, left["region_name"], right["region_name"]),
            ]
        )
        evidence = {
            "query_type": compare_request["query_type"],
            "sql": base_query_type,
            "compare_kind": "region_compare",
            "subqueries": subqueries,
            "comparisons": summaries,
            "analysis_context": {
                "domain": domain,
                "region_name": "",
                "region_level": "city",
                "query_type": compare_request["query_type"],
                "window": route_seed.get("window") or {},
            },
        }
        return {
            "mode": "data_query",
            "answer": answer,
            "data": summaries,
            "evidence": evidence,
        }

    region = str(compare_request["region"])
    base_mode = str(compare_request["base_query_type"])
    pest_query_type = f"pest_{base_mode}" if base_mode in {"detail", "trend", "overview"} else "pest_overview"
    soil_query_type = f"soil_{base_mode}" if base_mode in {"detail", "trend", "overview"} else "soil_overview"
    pest_route = dict(route_seed)
    pest_route.update({"query_type": pest_query_type, "city": region, "county": None, "region_level": "city"})
    soil_route = dict(route_seed)
    soil_route.update({"query_type": soil_query_type, "city": region, "county": None, "region_level": "city"})
    pest_result = query_engine.answer(question, plan=pest_route)
    soil_result = query_engine.answer(question, plan=soil_route)
    pest_summary = comparison_summary("pest", region, list(pest_result.data or []))
    soil_summary = comparison_summary("soil", region, list(soil_result.data or []))
    answer = "\n".join(
        [
            f"{region}{window_summary(route_seed.get('window'))}问题对比：",
            f"- 虫情：趋势{pest_summary['trend']}，均值{pest_summary['average']:.1f}，峰值{pest_summary['peak']:.1f}，最近值{pest_summary['latest']:.1f}",
            f"- 墒情：趋势{soil_summary['trend']}，均值{soil_summary['average']:.1f}，峰值{soil_summary['peak']:.1f}，最近值{soil_summary['latest']:.1f}",
            comparison_conclusion(pest_summary, soil_summary, "虫情", "墒情"),
        ]
    )
    evidence = {
        "query_type": compare_request["query_type"],
        "sql": "cross_domain_compare",
        "compare_kind": "cross_domain_compare",
        "subqueries": [
            {"domain": "pest", "query_type": pest_query_type, "region_name": region, "since": pest_route.get("since"), "until": pest_route.get("until")},
            {"domain": "soil", "query_type": soil_query_type, "region_name": region, "since": soil_route.get("since"), "until": soil_route.get("until")},
        ],
        "comparisons": [pest_summary, soil_summary],
        "analysis_context": {
            "domain": "mixed",
            "region_name": region,
            "region_level": infer_region_level_from_name(region) or "city",
            "query_type": compare_request["query_type"],
            "window": route_seed.get("window") or {},
        },
    }
    return {
        "mode": "data_query",
        "answer": answer,
        "data": [pest_summary, soil_summary],
        "evidence": evidence,
    }
