"""Deterministic fictional company ledgers, complete Q3 and Q4 through 2026-10-21.

Run with Python only. Does not import materials, clear records or call a model.
"""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

AS_OF = date(2026, 10, 21)
START = date(2026, 7, 1)
DEPARTMENTS = [
    (
        "TECH",
        "技术部",
        80,
        28,
        ["平台工程", "业务应用", "数据工程", "质量运维"],
        ["统一身份", "服务网关", "知识检索", "数据治理", "发布流水线", "监控告警", "备份恢复"],
        ["接口咨询", "权限申请", "故障处理", "发布支持"],
    ),
    (
        "RD",
        "研发部",
        56,
        22,
        ["产品研发", "算法研发", "测试验证", "研发效能"],
        ["需求协同", "智能检索", "文档识别", "客户门户", "测试平台", "组件库", "模型评测"],
        ["产品试用", "需求反馈", "缺陷修复", "交付咨询"],
    ),
    (
        "OPS",
        "运营部",
        40,
        18,
        ["客户运营", "内容运营", "流程运营", "服务运营"],
        ["客户交接", "订单异常", "服务知识库", "内容审核", "工单回访", "用户培训", "续约跟进"],
        ["工单咨询", "用户培训", "订单协调", "客户回访"],
    ),
    (
        "ADMIN",
        "行政部",
        24,
        12,
        ["综合行政", "资产管理", "办公服务", "采购协调"],
        ["会议预约", "资产领用", "报修闭环", "采购协同", "档案借阅", "差旅支持", "工位管理"],
        ["会议支持", "物业报修", "办公用品", "差旅支持"],
    ),
]
PERIODS = [
    ("2026Q3", START, date(2026, 10, 1)),
    ("2026Q4截至10月21日", date(2026, 10, 1), AS_OF + timedelta(days=1)),
]


def days(start, end):
    return [
        start + timedelta(days=i)
        for i in range((end - start).days)
        if (start + timedelta(days=i)).weekday() < 5
    ]


def number(*parts):
    return int.from_bytes(hashlib.sha256("|".join(map(str, parts)).encode()).digest()[:4], "big")


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def generate(output):
    output = Path(output)
    manifest = dict(
        fictional=True,
        company="衡川数智（虚构）",
        as_of=AS_OF.isoformat(),
        seed="enterprise-office-v1",
        files=[],
        departments=[],
    )
    for dept_index, (code, department, people, project_count, teams, themes, services) in enumerate(
        DEPARTMENTS
    ):
        projects = []
        for i in range(1, project_count + 1):
            launched = START + timedelta(days=(i % 5) * 3)
            finish = START + timedelta(days=38 + i * 4 + dept_index * 7)
            paused = i % 11 == 0
            projects.append(
                dict(
                    project_id=f"ENT-{code}-P{i:03}",
                    name=f"{themes[(i - 1) % len(themes)]}·{(i - 1) // len(themes) + 1}期",
                    launched=launched,
                    finish=finish,
                    paused=paused,
                    due=finish - timedelta(days=7 if i % 5 == 0 else -3),
                    owner=f"ENT-{code}-U{1 + (i - 1) * 3 % people:03}",
                    team=teams[(i - 1) % len(teams)],
                )
            )
        manifest["departments"].append(
            dict(name=department, roster_size=people, projects=project_count)
        )
        for period, start, end in PERIODS:
            workdays = days(start, end)
            snapshots = sorted(
                {day for day in workdays if day.weekday() == 4} | {end - timedelta(days=1)}
            )
            project_rows, attendance, achievements, feedback = [], [], [], []
            for project in projects:
                for snapshot in snapshots:
                    if snapshot < project["launched"]:
                        continue
                    completed = not project["paused"] and project["finish"] <= snapshot
                    paused = project["paused"] and snapshot >= date(2026, 8, 21)
                    progress = (
                        100
                        if completed
                        else min(
                            95,
                            max(
                                5,
                                int(
                                    100
                                    * (snapshot - project["launched"]).days
                                    / (project["finish"] - project["launched"]).days
                                ),
                            ),
                        )
                    )
                    if paused:
                        progress = min(progress, 58)
                    project_rows.append(
                        dict(
                            project_id=project["project_id"],
                            department=department,
                            effective_date=project["launched"].isoformat(),
                            snapshot_date=snapshot.isoformat(),
                            status="completed"
                            if completed
                            else "paused"
                            if paused
                            else "in_progress",
                            progress=progress,
                            completed_date=project["finish"].isoformat() if completed else "",
                            project_name=project["name"],
                            owner_id=project["owner"],
                            team=project["team"],
                            planned_due_date=project["due"].isoformat(),
                            risk_level="高"
                            if paused
                            else "中"
                            if not completed and snapshot > project["due"]
                            else "低",
                            blocker="外部接口验收依赖未解除" if paused else "",
                            fictional="true",
                        )
                    )
                milestones = [
                    (project["launched"] + timedelta(days=14), "需求评审", "需求范围与验收清单"),
                    (
                        project["launched"] + timedelta(days=35),
                        "阶段交付",
                        "阶段功能验证与问题清单",
                    ),
                    (project["finish"], "项目交付", "验收签认与运行交接"),
                ]
                for sequence, (day, category, title) in enumerate(milestones, 1):
                    if not start <= day < end or project["paused"] and sequence == 3:
                        continue
                    achievements.append(
                        dict(
                            achievement_id=f"{project['project_id']}-A{sequence}",
                            department=department,
                            date=day.isoformat(),
                            category=category,
                            name=project["name"] + "：" + title,
                            project_id=project["project_id"],
                            owner_id=project["owner"],
                            evidence_id=f"{project['project_id']}-E{sequence}",
                            acceptance_status="已确认",
                            fictional="true",
                        )
                    )
            for day in workdays:
                for person in range(1, people + 1):
                    joined = date(2026, 9, 1) if person % 10 == 0 else START
                    left = date(2026, 9, 18) if person % 23 == 0 else None
                    if day < joined or left and day > left:
                        continue
                    person_id = f"ENT-{code}-U{person:03}"
                    bucket = number("attendance", person_id, day) % 1000
                    actual, leave, absent, late = 8, 0, 0, 0
                    status, leave_type, reason = "正常", "", "日常实施与业务交接"
                    if bucket < 5:
                        actual, absent, status, reason = 0, 8, "缺勤", "考勤异常待核实"
                    elif bucket < 82:
                        leave = 8 if bucket < 25 else 4 if bucket < 58 else 2
                        actual, status, leave_type, reason = (
                            8 - leave,
                            "请假",
                            ("事假", "病假", "调休")[bucket % 3],
                            "模拟审批记录已确认",
                        )
                    elif bucket < 135:
                        late = 15 if bucket % 2 else 30
                        actual, status, reason = 8 - late / 60, "迟到", "迟到已反映在实际工时"
                    elif bucket < 210:
                        actual, status, reason = (
                            9 + bucket % 2,
                            "超计划工时",
                            "发布支持或业务高峰，未等同于审批加班",
                        )
                    attendance.append(
                        dict(
                            person_id=person_id,
                            department=department,
                            date=day.isoformat(),
                            planned_hours=8,
                            actual_hours=f"{actual:g}",
                            leave_hours=leave,
                            absent_hours=absent,
                            late_minutes=late,
                            team=teams[(person - 1) % len(teams)],
                            project_id=projects[(person - 1) % project_count]["project_id"],
                            attendance_status=status,
                            leave_type=leave_type,
                            work_note=reason,
                            employment_start=joined.isoformat(),
                            employment_end=left.isoformat() if left else "",
                            fictional="true",
                        )
                    )
                for sequence in range(8 + number("tickets", code, day) % 7):
                    uid = f"ENT-{code}-{day:%Y%m%d}-{sequence + 1:02}"
                    bucket = number("score", uid) % 100
                    score = (
                        5
                        if bucket < 43
                        else 4
                        if bucket < 77
                        else 3
                        if bucket < 92
                        else 2
                        if bucket < 98
                        else 1
                    )
                    invalid = number("invalid", uid) % 61 == 0
                    feedback.append(
                        dict(
                            feedback_id=uid + "-F",
                            department=department,
                            date=day.isoformat(),
                            score=score,
                            scale_min=1,
                            scale_max=5,
                            valid="false" if invalid else "true",
                            ticket_id=uid + "-T",
                            service_type=services[sequence % len(services)],
                            requester_id=f"ENT-REQ-{1 + number('requester', uid) % 300:03}",
                            created_date=(day - timedelta(days=2)).isoformat(),
                            resolved_date=(day - timedelta(days=1)).isoformat(),
                            channel=("服务门户", "企业消息", "现场登记")[sequence % 3],
                            comment="服务符合预期"
                            if score >= 4
                            else "交接说明仍可完善"
                            if score == 3
                            else "状态告知不足，需跟进复核",
                            invalid_reason="内部演练提交，复核后剔除" if invalid else "",
                            fictional="true",
                        )
                    )
            latest = [
                row for row in project_rows if row["snapshot_date"] == snapshots[-1].isoformat()
            ]
            states = dict(Counter(row["status"] for row in latest))
            notes = (
                "\n".join(
                    [
                        "衡川数智（虚构）办公工作记录。全部记录为确定性合成数据，不含真实员工或客户信息。",
                        f"范围：{department}；{start}（含）至{end}（不含）。"
                        f"数据截点为{end - timedelta(days=1)}。",
                        "业务链路：项目台账按周留存快照；人员、成果均关联项目；反馈通过服务单编号关联受理及办结记录。",
                        "组织分工："
                        + "；".join(teams)
                        + "。负责人使用模拟编号，保留组别以便分组复盘。",
                        "项目进度为阶段估计；暂停事项由负责人协调外部验收依赖，完成仅代表台账验收，不等于收益已经实现。",
                        "成果包含需求评审、阶段交付和验收交接，不将所有阶段成果重复算作项目完成。",
                        "人员有入职和离职变动，仅在在岗期间记人日；采用虚构周一至周五排班，未套用法定节假日与调休。",
                        "请假、缺勤均保留应计划工时；迟到已体现在实际工时内；超计划工时单列，不提高出勤率。",
                        "服务反馈均为相同五分量表；保留低分与无效样本，无效样本留原始评分和剔除原因。反馈不是服务总量或全部员工意见。",
                        "低分事项由服务负责人回访确认，补齐沟通记录后复核；没有改善前后对照，不宣称满意度提升由单项措施造成。",
                        "风险跟进：外部接口依赖、逾期交付、考勤异常及低分反馈分别形成待核事项，不因汇报生成而自动视为闭环。",
                        "后续安排：优先处理暂停与逾期项目的验收依赖，复核低分反馈，检查新增人员与离岗人员的交接完整性。",
                        "第四季度仅截至10月21日，不能据当前累计推算整季业绩；未提供预算、收入、成本和同比基线，不编造经营结论。",
                        "统计数值以同组CSV经Data工具计算为准；文件行数不是项目总数，跨期间比较须先统一范围和口径。",
                    ]
                )
                + "\n"
            )
            entries = [
                ("项目进度.csv", "projects", project_rows),
                ("人员考勤.csv", "attendance", attendance),
                ("成果统计.csv", "achievements", achievements),
                ("满意度.csv", "satisfaction", feedback),
                ("工作说明.txt", "notes", notes),
            ]
            for suffix, kind, content in entries:
                name = f"{department}_{period}_{suffix}"
                raw = content.encode() if isinstance(content, str) else csv_bytes(content)
                relative = f"{code.lower()}/{period}/{name}"
                path = output / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                manifest["files"].append(
                    dict(
                        path=relative,
                        name=name,
                        kind=kind,
                        department=department,
                        start_date=start.isoformat(),
                        end_date=end.isoformat(),
                        rows=len(content.splitlines())
                        if isinstance(content, str)
                        else len(content),
                        sha256=hashlib.sha256(raw).hexdigest(),
                    )
                )
            manifest.setdefault("expected", []).append(
                dict(
                    department=department,
                    period=period,
                    project_count=len(latest),
                    project_states=states,
                    attendance_rows=len(attendance),
                    people=len({row["person_id"] for row in attendance}),
                    achievements=len(achievements),
                    feedback=len(feedback),
                    valid_feedback=sum(row["valid"] == "true" for row in feedback),
                )
            )
    manifest["total_rows"] = sum(item["rows"] for item in manifest["files"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    result = generate(args.output)
    print(
        json.dumps(
            dict(
                files=len(result["files"]),
                total_rows=result["total_rows"],
                expected=result["expected"],
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
