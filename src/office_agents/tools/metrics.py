"""Deterministic, traceable statistics over a fully validated data set."""

from pathlib import Path

from office_agents.schemas import (
    DataIssue,
    DataRequest,
    DataResult,
    Metric,
    ProjectSnapshot,
    SourceRef,
    ValidatedDataset,
)


def _ordered_refs(refs: list[SourceRef]) -> list[SourceRef]:
    return sorted(refs, key=lambda ref: (ref.source_id, ref.line_number))


def calculate_metrics(dataset: ValidatedDataset, request: DataRequest) -> DataResult:
    """Filter a half-open date range and count each project's latest snapshot once.

    Validation must cover the whole dataset before filtering. Any validation error
    blocks all metrics and raw issue material, including errors outside the request.
    """
    sources = sorted(dataset.sources, key=lambda source: source.source_id)
    issues = list(dataset.data_issues)
    if any(issue.severity == "error" for issue in issues):
        return DataResult(
            status="invalid_data", request=request, sources=sources, data_issues=issues
        )

    latest: dict[str, ProjectSnapshot] = {}
    for snapshot in sorted(
        dataset.projects,
        key=lambda row: (row.project_id, row.snapshot_date, row.source.line_number),
    ):
        if (
            snapshot.department == request.department
            and request.start_date <= snapshot.snapshot_date < request.end_date
        ):
            latest[snapshot.project_id] = snapshot
    projects = list(latest.values())
    completed = [project for project in projects if project.status == "completed"]
    achievements = [
        achievement
        for achievement in dataset.achievements
        if achievement.department == request.department
        and request.start_date <= achievement.date < request.end_date
    ]
    project_refs = _ordered_refs([project.source for project in projects])
    completed_refs = _ordered_refs([project.source for project in completed])
    achievement_refs = _ordered_refs([achievement.source for achievement in achievements])
    if not projects:
        issues.append(
            DataIssue(
                severity="warning",
                code="no_projects",
                message="所选部门和日期区间无项目快照，完成率没有分母，返回 null。",
                source_id="projects.csv",
            )
        )
    metrics = [
        Metric(
            metric_id="project_count",
            value=len(projects),
            unit="count",
            definition=(
                "部门精确匹配，快照日期属于 [start_date, end_date)；"
                "每个 project_id 仅选区间内最新快照，按项目编号计数。"
            ),
            source_ids=["projects.csv"],
            source_refs=project_refs,
        ),
        Metric(
            metric_id="completed_project_count",
            value=len(completed),
            unit="count",
            definition="所选项目区间内最新快照的 status=completed 的项目数。",
            source_ids=["projects.csv"],
            source_refs=completed_refs,
        ),
        Metric(
            metric_id="completion_rate",
            value=len(completed) / len(projects) if projects else None,
            unit="ratio",
            definition=(
                "completed_project_count / project_count，返回 0～1 原始比例；"
                "来源包含全部分母项目，分子由这些最新快照的状态决定；"
                "项目数为零时返回 null。"
            ),
            source_ids=["projects.csv"],
            source_refs=project_refs,
        ),
        Metric(
            metric_id="achievement_count",
            value=len(achievements),
            unit="count",
            definition=(
                "部门精确匹配，成果日期属于 [start_date, end_date)；"
                "按已校验且去重的 achievement_id 计数。"
            ),
            source_ids=["achievements.csv"],
            source_refs=achievement_refs,
        ),
    ]
    return DataResult(
        status="ok" if projects or achievements else "no_data",
        request=request,
        metrics=metrics,
        sources=sources,
        data_issues=issues,
        issue_materials=sorted(dataset.issue_materials, key=lambda material: material.source_id),
    )


def run_data_tools(data_root: str | Path, request: DataRequest) -> DataResult:
    """Read and validate the authorized directory before calculating any metrics."""
    from office_agents.tools.data_io import validate_data

    return calculate_metrics(validate_data(data_root), request)
