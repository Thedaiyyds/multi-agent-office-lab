"""Small file inventory for planning; business statistics remain the Data role's job."""

from datetime import date, timedelta


def material_profile(materials):
    files, scopes = [], set()
    for material in materials:
        periods = set()
        if material["kind"] == "notes":
            periods.add((material["department"], material["start_date"], material["end_date"]))
        else:
            mapping = material["mapping"]
            day_field = "snapshot_date" if material["kind"] == "projects" else "date"
            for row in material["rows"]:
                department = row["values"][mapping["department"]]
                day = date.fromisoformat(row["values"][mapping[day_field]])
                month = ((day.month - 1) // 3) * 3 + 1
                start = date(day.year, month, 1)
                end = date(day.year + 1, 1, 1) if month == 10 else date(day.year, month + 3, 1)
                periods.add((department, start.isoformat(), end.isoformat()))
                if len(periods) > 48:
                    raise ValueError("材料涉及的部门或期间过多，请先拆分文件")
        scopes.update(periods)
        if len(scopes) > 48:
            raise ValueError("材料涉及的部门或期间过多，请缩小文件选择范围")
        files.append(
            dict(
                id=material["id"],
                name=material["name"],
                kind=material["kind"],
                sha256=material["sha256"],
                row_count=material["row_count"],
                scopes=[
                    dict(department=d, start_date=s, end_date=e) for d, s, e in sorted(periods)
                ],
            )
        )
    # A monthly note within a quarter doesn't create a competing report scope.
    scopes = {
        scope
        for scope in scopes
        if not any(
            scope != other
            and scope[0] == other[0]
            and other[1] <= scope[1]
            and scope[2] <= other[2]
            for other in scopes
        )
    }
    return dict(
        files=files,
        scopes=[dict(department=d, start_date=s, end_date=e) for d, s, e in sorted(scopes)],
    )


def scope_supported(requirements, profile):
    return any(
        item["department"] == requirements["department"]
        and item["start_date"]
        <= requirements["start_date"]
        < requirements["end_date"]
        <= item["end_date"]
        for item in profile["scopes"]
    )


def scope_title(scope):
    start, end = date.fromisoformat(scope["start_date"]), date.fromisoformat(scope["end_date"])
    month = ((start.month - 1) // 3) * 3 + 1
    quarter_end = date(start.year + 1, 1, 1) if month == 10 else date(start.year, month + 3, 1)
    period = (
        f"{start.year}年第{'一二三四'[(month - 1) // 3]}季度"
        if start.day == 1 and start.month == month and end == quarter_end
        else f"{start}至{end - timedelta(days=1)}"
    )
    return period + scope["department"] + "工作汇报"


def plan_evidence(requirements, outline, profile):
    applicable = [
        item
        for item in profile["files"]
        if any(
            scope["department"] == requirements["department"]
            and scope["start_date"] < requirements["end_date"]
            and requirements["start_date"] < scope["end_date"]
            for scope in item["scopes"]
        )
    ]
    groups = {item["kind"] for item in applicable}
    names = {
        "projects": "项目进度",
        "attendance": "人员考勤",
        "achievements": "成果统计",
        "satisfaction": "服务满意度",
    }
    gaps = [
        f"缺少{names[group]}材料，生成前需要补充或调整该章节的数据要求。"
        for group in outline["groups"]
        if group not in groups
    ]
    if "notes" not in groups:
        gaps.append("缺少文字说明：问题原因、工作复盘和后续安排只能作为建议，不能写成已确认事实。")
    if "attendance" in groups:
        gaps.append(
            "考勤仅代表提供的样本，未提供完整人员名单和应出勤日历时，不能认定部门整体出勤率。"
        )
    if not outline["groups"]:
        gaps.append("本方案为文字工作汇报，不生成项目、考勤等量化统计，也不能据文字说明推算指标。")
    gaps.append(
        "文件记录和日期只说明材料范围，不保证整期数据完整；预算等未提供的数据不作事实结论。"
    )
    return dict(
        gaps=gaps,
        sections=[
            dict(
                title=section["title"],
                material_ids=[
                    item["id"]
                    for item in applicable
                    if item["kind"] == "notes" or item["kind"] in section["groups"]
                ],
            )
            for section in outline["sections"]
        ],
    )
