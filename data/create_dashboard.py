"""Create the ClearOne Advantage operational dashboard via QuickSight API.

Builds a multi-sheet dashboard:
  1. Portfolio Overview  — KPIs and client breakdown
  2. Settlement Performance — negotiator outcomes by creditor/team
  3. Agent Productivity  — daily agent metrics
  4. Call Center Ops     — queue-level call metrics
"""
from __future__ import annotations

import sys
import uuid

import boto3

import os

ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID") or boto3.client("sts").get_caller_identity()["Account"]
REGION = os.environ.get("AWS_REGION", "us-west-2")
ADMIN_USER_NAME = os.environ.get("QS_ADMIN_USER_NAME")
if not ADMIN_USER_NAME:
    raise SystemExit("Set QS_ADMIN_USER_NAME (e.g. 'Admin/your-iam-username') from `aws quicksight list-users`")
ADMIN_ARN = f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:user/default/{ADMIN_USER_NAME}"

DATASETS = {
    "clients": f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:dataset/clearone-clients",
    "negotiations": f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:dataset/clearone-negotiations",
    "payments": f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:dataset/clearone-payments",
    "agent_perf": f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:dataset/clearone-agent-performance",
    "calls": f"arn:aws:quicksight:{REGION}:{ACCOUNT_ID}:dataset/clearone-call-activity",
}

DS_IDENT = {
    "clients": "clients_ds",
    "negotiations": "negotiations_ds",
    "payments": "payments_ds",
    "agent_perf": "agent_perf_ds",
    "calls": "calls_ds",
}

qs = boto3.client("quicksight", region_name=REGION)


def dataset_identifier_declarations() -> list[dict]:
    return [
        {"Identifier": DS_IDENT[k], "DataSetArn": DATASETS[k]} for k in DATASETS
    ]


def col(ds: str, name: str) -> dict:
    return {"DataSetIdentifier": DS_IDENT[ds], "ColumnName": name}


_STRING_COUNT_COLS = {
    "client_id", "first_name", "last_name", "state", "status",
    "enrollment_source", "assigned_specialist", "assigned_negotiator",
    "assigned_cs", "negotiation_id", "creditor", "outcome", "negotiator_id",
    "payment_id", "failure_reason", "agent_id", "agent_name", "role",
    "office", "team", "queue",
}


def measure(ds: str, name: str, agg: str, measure_id: str | None = None) -> dict:
    """Build a measure field. Use CategoricalMeasureField for COUNT/DISTINCT_COUNT
    on string columns; NumericalMeasureField for SUM/AVG/etc on numerics.
    """
    fid = measure_id or f"m_{ds}_{name}_{agg}"
    if name in _STRING_COUNT_COLS:
        if agg in ("COUNT", "DISTINCT_COUNT"):
            return {
                "CategoricalMeasureField": {
                    "FieldId": fid,
                    "Column": col(ds, name),
                    "AggregationFunction": "COUNT" if agg == "COUNT" else "DISTINCT_COUNT",
                }
            }
        raise ValueError(f"Cannot use aggregation {agg!r} on string column {name!r}")
    return {
        "NumericalMeasureField": {
            "FieldId": fid,
            "Column": col(ds, name),
            "AggregationFunction": {"SimpleNumericalAggregation": agg},
        }
    }


def category(ds: str, name: str, cat_id: str | None = None) -> dict:
    return {
        "CategoricalDimensionField": {
            "FieldId": cat_id or f"c_{ds}_{name}",
            "Column": col(ds, name),
        }
    }


def date_dim(ds: str, name: str, granularity: str, field_id: str | None = None) -> dict:
    return {
        "DateDimensionField": {
            "FieldId": field_id or f"d_{ds}_{name}_{granularity}",
            "Column": col(ds, name),
            "DateGranularity": granularity,
        }
    }


def kpi_visual(visual_id: str, title: str, ds: str, measure_name: str, agg: str = "SUM") -> dict:
    return {
        "KPIVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "Values": [measure(ds, measure_name, agg, f"kpi_{visual_id}_val")],
                },
            },
        }
    }


def pie_visual(visual_id: str, title: str, ds: str, group_name: str, value_name: str, agg: str = "COUNT") -> dict:
    return {
        "PieChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "PieChartAggregatedFieldWells": {
                        "Category": [category(ds, group_name, f"pie_{visual_id}_cat")],
                        "Values": [measure(ds, value_name, agg, f"pie_{visual_id}_val")],
                    }
                },
                "DonutOptions": {"ArcOptions": {"ArcThickness": "MEDIUM"}},
            },
        }
    }


def bar_visual(visual_id: str, title: str, ds: str, category_name: str,
               value_name: str, agg: str = "SUM", horizontal: bool = True) -> dict:
    return {
        "BarChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "BarChartAggregatedFieldWells": {
                        "Category": [category(ds, category_name, f"bar_{visual_id}_cat")],
                        "Values": [measure(ds, value_name, agg, f"bar_{visual_id}_val")],
                    }
                },
                "Orientation": "HORIZONTAL" if horizontal else "VERTICAL",
                "SortConfiguration": {
                    "CategorySort": [{
                        "FieldSort": {
                            "FieldId": f"bar_{visual_id}_val",
                            "Direction": "DESC",
                        }
                    }],
                    "CategoryItemsLimit": {"ItemsLimit": 15},
                },
            },
        }
    }


def line_visual(visual_id: str, title: str, ds: str, date_field: str,
                value_name: str, agg: str = "SUM", granularity: str = "DAY") -> dict:
    return {
        "LineChartVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {
                    "LineChartAggregatedFieldWells": {
                        "Category": [date_dim(ds, date_field, granularity, f"line_{visual_id}_date")],
                        "Values": [measure(ds, value_name, agg, f"line_{visual_id}_val")],
                    }
                },
            },
        }
    }


def table_visual(visual_id: str, title: str, ds: str, columns: list[tuple[str, str]]) -> dict:
    """columns: list of (field_type, column_name). field_type in {'cat','msum','mavg','mcount'}."""
    fields = []
    order = []
    for i, (ft, cn) in enumerate(columns):
        fid = f"tbl_{visual_id}_f{i}"
        order.append({"FieldId": fid, "Width": "120px"})
        if ft == "cat":
            fields.append({"CategoricalDimensionField": {"FieldId": fid, "Column": col(ds, cn)}})
        elif ft == "date":
            fields.append({"DateDimensionField": {"FieldId": fid, "Column": col(ds, cn), "DateGranularity": "DAY"}})
        else:
            agg = {"msum": "SUM", "mavg": "AVERAGE", "mcount": "COUNT"}[ft]
            fields.append({
                "NumericalMeasureField": {
                    "FieldId": fid,
                    "Column": col(ds, cn),
                    "AggregationFunction": {"SimpleNumericalAggregation": agg},
                }
            })
    return {
        "TableVisual": {
            "VisualId": visual_id,
            "Title": {"Visibility": "VISIBLE", "FormatText": {"PlainText": title}},
            "ChartConfiguration": {
                "FieldWells": {"TableAggregatedFieldWells": {"GroupBy": [fields[0]], "Values": fields[1:]}},
                "FieldOptions": {"SelectedFieldOptions": order},
            },
        }
    }


def sheet(sheet_id: str, name: str, visuals: list[dict], layout_rows: list[list[tuple[str, int]]]) -> dict:
    """Create a sheet with a grid layout. layout_rows is list of rows, each row is list of (visualId, span)."""
    grid_elements = []
    row_height = 6
    row_y = 0
    for row in layout_rows:
        spans = [s for _, s in row]
        total = sum(spans)
        x = 0
        for vid, span in row:
            width = (span / total) * 36
            grid_elements.append({
                "ElementId": vid,
                "ElementType": "VISUAL",
                "ColumnIndex": int(x),
                "ColumnSpan": max(1, int(width)),
                "RowIndex": row_y,
                "RowSpan": row_height,
            })
            x += width
        row_y += row_height
    return {
        "SheetId": sheet_id,
        "Name": name,
        "Visuals": visuals,
        "Layouts": [{
            "Configuration": {
                "GridLayout": {
                    "Elements": grid_elements,
                    "CanvasSizeOptions": {
                        "ScreenCanvasSizeOptions": {"ResizeOption": "RESPONSIVE"}
                    },
                }
            }
        }],
    }


def build_definition() -> dict:
    # Sheet 1: Portfolio Overview
    s1_visuals = [
        kpi_visual("kpi1a", "Total Enrolled Debt", "clients", "total_enrolled_debt", "SUM"),
        kpi_visual("kpi1b", "Active Clients", "clients", "client_id", "COUNT"),
        kpi_visual("kpi1c", "Avg Monthly Deposit", "clients", "monthly_deposit", "AVERAGE"),
        kpi_visual("kpi1d", "Total Enrolled Accounts", "clients", "enrolled_accounts", "SUM"),
        pie_visual("pie1a", "Clients by Status", "clients", "status", "client_id", "COUNT"),
        pie_visual("pie1b", "Enrollment Source Mix", "clients", "enrollment_source", "client_id", "COUNT"),
        bar_visual("bar1a", "Top 15 States by Enrolled Debt", "clients", "state", "total_enrolled_debt", "SUM"),
        line_visual("line1a", "Monthly Enrollments (trailing)", "clients", "enrollment_date",
                    "client_id", "COUNT", "MONTH"),
    ]
    sheet1 = sheet(
        "sheet_portfolio",
        "Portfolio Overview",
        s1_visuals,
        [
            [("kpi1a", 1), ("kpi1b", 1), ("kpi1c", 1), ("kpi1d", 1)],
            [("pie1a", 1), ("pie1b", 1), ("bar1a", 2)],
            [("line1a", 1)],
        ],
    )

    # Sheet 2: Settlement Performance
    s2_visuals = [
        kpi_visual("kpi2a", "Total Settlements Accepted", "negotiations", "negotiation_id", "COUNT"),
        kpi_visual("kpi2b", "Total Client Savings", "negotiations", "savings", "SUM"),
        kpi_visual("kpi2c", "Avg Settlement %", "negotiations", "settlement_percentage", "AVERAGE"),
        kpi_visual("kpi2d", "Total Original Balance", "negotiations", "original_balance", "SUM"),
        bar_visual("bar2a", "Top Creditors by Savings", "negotiations", "creditor", "savings", "SUM"),
        pie_visual("pie2a", "Outcome Distribution", "negotiations", "outcome", "negotiation_id", "COUNT"),
        line_visual("line2a", "Monthly Settlement Savings", "negotiations", "negotiation_date",
                    "savings", "SUM", "MONTH"),
        bar_visual("bar2b", "Savings by Negotiator", "negotiations", "negotiator_id",
                   "savings", "SUM", horizontal=True),
    ]
    sheet2 = sheet(
        "sheet_settlements",
        "Settlement Performance",
        s2_visuals,
        [
            [("kpi2a", 1), ("kpi2b", 1), ("kpi2c", 1), ("kpi2d", 1)],
            [("bar2a", 2), ("pie2a", 1)],
            [("line2a", 2), ("bar2b", 1)],
        ],
    )

    # Sheet 3: Agent Productivity
    s3_visuals = [
        kpi_visual("kpi3a", "Total Calls Handled", "agent_perf", "calls_handled", "SUM"),
        kpi_visual("kpi3b", "Total Enrollments Signed", "agent_perf", "enrollments_signed", "SUM"),
        kpi_visual("kpi3c", "Avg CSAT Score", "agent_perf", "csat_score", "AVERAGE"),
        kpi_visual("kpi3d", "Total Talk Time (min)", "agent_perf", "talk_time_minutes", "SUM"),
        bar_visual("bar3a", "Enrollments by Team", "agent_perf", "team", "enrollments_signed", "SUM"),
        pie_visual("pie3a", "Calls by Office", "agent_perf", "office", "calls_handled", "SUM"),
        line_visual("line3a", "Daily Calls Handled", "agent_perf", "date", "calls_handled", "SUM", "DAY"),
        table_visual("tbl3a", "Agent Leaderboard (sum)", "agent_perf", [
            ("cat", "agent_name"),
            ("msum", "calls_handled"),
            ("msum", "enrollments_signed"),
            ("msum", "settlements_closed"),
            ("mavg", "csat_score"),
        ]),
    ]
    sheet3 = sheet(
        "sheet_agents",
        "Agent Productivity",
        s3_visuals,
        [
            [("kpi3a", 1), ("kpi3b", 1), ("kpi3c", 1), ("kpi3d", 1)],
            [("bar3a", 2), ("pie3a", 1)],
            [("line3a", 2), ("tbl3a", 1)],
        ],
    )

    # Sheet 4: Call Center Ops
    s4_visuals = [
        kpi_visual("kpi4a", "Calls Offered", "calls", "calls_offered", "SUM"),
        kpi_visual("kpi4b", "Calls Answered", "calls", "calls_answered", "SUM"),
        kpi_visual("kpi4c", "Calls Abandoned", "calls", "calls_abandoned", "SUM"),
        kpi_visual("kpi4d", "Avg Service Level %", "calls", "service_level_pct", "AVERAGE"),
        pie_visual("pie4a", "Queue Volume Mix", "calls", "queue", "calls_offered", "SUM"),
        bar_visual("bar4a", "Avg Wait by Queue (sec)", "calls", "queue", "avg_wait_seconds", "AVERAGE"),
        line_visual("line4a", "Daily Calls Offered", "calls", "date", "calls_offered", "SUM", "DAY"),
        line_visual("line4b", "Daily Service Level %", "calls", "date", "service_level_pct", "AVERAGE", "DAY"),
    ]
    sheet4 = sheet(
        "sheet_call_center",
        "Call Center Ops",
        s4_visuals,
        [
            [("kpi4a", 1), ("kpi4b", 1), ("kpi4c", 1), ("kpi4d", 1)],
            [("pie4a", 1), ("bar4a", 1)],
            [("line4a", 1), ("line4b", 1)],
        ],
    )

    return {
        "DataSetIdentifierDeclarations": dataset_identifier_declarations(),
        "Sheets": [sheet1, sheet2, sheet3, sheet4],
        "AnalysisDefaults": {
            "DefaultNewSheetConfiguration": {
                "InteractiveLayoutConfiguration": {"Grid": {"CanvasSizeOptions": {
                    "ScreenCanvasSizeOptions": {"ResizeOption": "RESPONSIVE"}
                }}},
                "SheetContentType": "INTERACTIVE",
            }
        },
    }


def main() -> None:
    definition = build_definition()

    analysis_id = "clearone-operations-analysis"
    dashboard_id = "clearone-operations-dashboard"

    permissions_analysis = [{
        "Principal": ADMIN_ARN,
        "Actions": [
            "quicksight:RestoreAnalysis",
            "quicksight:UpdateAnalysisPermissions",
            "quicksight:DeleteAnalysis",
            "quicksight:DescribeAnalysisPermissions",
            "quicksight:QueryAnalysis",
            "quicksight:DescribeAnalysis",
            "quicksight:UpdateAnalysis",
        ],
    }]
    permissions_dashboard = [{
        "Principal": ADMIN_ARN,
        "Actions": [
            "quicksight:DescribeDashboard",
            "quicksight:ListDashboardVersions",
            "quicksight:UpdateDashboardPermissions",
            "quicksight:QueryDashboard",
            "quicksight:UpdateDashboard",
            "quicksight:DeleteDashboard",
            "quicksight:DescribeDashboardPermissions",
            "quicksight:UpdateDashboardPublishedVersion",
        ],
    }]

    try:
        qs.delete_analysis(AwsAccountId=ACCOUNT_ID, AnalysisId=analysis_id, ForceDeleteWithoutRecovery=True)
        print(f"deleted existing analysis {analysis_id}")
    except qs.exceptions.ResourceNotFoundException:
        pass
    try:
        qs.delete_dashboard(AwsAccountId=ACCOUNT_ID, DashboardId=dashboard_id)
        print(f"deleted existing dashboard {dashboard_id}")
    except qs.exceptions.ResourceNotFoundException:
        pass

    print("creating analysis...")
    a = qs.create_analysis(
        AwsAccountId=ACCOUNT_ID,
        AnalysisId=analysis_id,
        Name="ClearOne Operations Analysis",
        Definition=definition,
        Permissions=permissions_analysis,
    )
    print(f"  analysis arn: {a['Arn']}")

    print("creating dashboard...")
    d = qs.create_dashboard(
        AwsAccountId=ACCOUNT_ID,
        DashboardId=dashboard_id,
        Name="ClearOne Advantage — Operations",
        Definition=definition,
        Permissions=permissions_dashboard,
        DashboardPublishOptions={
            "AdHocFilteringOption": {"AvailabilityStatus": "ENABLED"},
            "ExportToCSVOption": {"AvailabilityStatus": "ENABLED"},
            "SheetControlsOption": {"VisibilityState": "EXPANDED"},
        },
    )
    print(f"  dashboard id: {dashboard_id}")
    print(f"  dashboard arn: {d['Arn']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
