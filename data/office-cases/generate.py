"""Rebuild the explicitly fictional office cases using only the standard library.

No personal data, network, wall clock, PRNG implementation, or model is involved.
The case seed and SHA-256 event formula are part of the published data contract.
"""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

SEED = "office-cases-2026-v1"
PROJECTS = [
    ("统一权限中心改造", [70, 100, 100], "2026-05-12", "2026-05-15"),
    ("内部知识库检索升级", [45, 78, 100], "2026-06-18", "2026-06-19"),
    ("工单智能分流规则优化", [100, 100, 100], "2026-04-23", "2026-04-24"),
    ("监控告警收敛治理", [30, 65, 100], "2026-06-26", "2026-06-26"),
    ("内部接口网关升级", [60, 100, 100], "2026-05-27", "2026-05-29"),
    ("移动审批流程改造", [15, 60, 100], "2026-06-30", "2026-06-30"),
    ("资产服务门户", [35, 65, 95], "", "2026-07-10"),
    ("主数据质量规则建设", [20, 55, 85], "", "2026-07-17"),
    ("跨可用区备份恢复演练", [15, 40, 68], "", "2026-07-24"),
    ("发布流水线权限改造", [25, 45, 45], "", "2026-07-31"),
    ("日志脱敏规则迭代", [10, 30, 55], "", "2026-08-14"),
    ("历史档案检索索引", [5, 15, 30], "", "2026-08-28"),
]
TEAMS = ["平台工程组", "业务应用组", "数据工程组", "质量运维组"]
SERVICE_TYPES = ["会议支持", "物业报修", "办公用品", "差旅支持", "入离职支持", "档案借阅"]
SERVICE_COUNTS = [[18, 16, 14, 10, 8, 6], [16, 18, 12, 12, 8, 6], [20, 14, 12, 10, 10, 6]]
TECH_NOTES = (
    "虚构案例：衡川数智技术部季度工作记录。企业、人员编号、项目和记录均为合成数据，不代表真实单位。\n"
    "范围：技术部；开始日2026-04-01，结束日2026-07-01（不含结束日）；结构化数值以同目录CSV和系统统计为准。\n"
    "排班口径：本案例采用周一至周五的虚构企业工作日历，未按法定节假日或调休排班，不用于真实考勤、工资或合规判断。\n"
    "组织分工：平台工程组负责访问与服务底座；业务应用组负责办公流程；数据工程组负责数据与恢复能力；质量运维组负责交付工具和安全规则。\n"
    "项目口径：项目进度表为本案例项目台账月末快照；进度是责任人估计的阶段完成度，不是工作量、工期或收益指标。未附真实企业完整项目主档，汇报应使用可识别项目表述。\n"
    "材料关系：成果编号唯一，成果关联的项目编号可在进度表查到；项目交付成果发生日与项目实际完成日一致；文档、测试和运行手册也属于阶段成果，不等于项目整体完成。\n"
    "已交付事项：统一权限中心完成灰度验收并形成回滚手册；知识库检索完成常用问题回归；工单分流规则交接给服务台；监控告警、接口网关与移动审批均有交付记录。\n"
    "平台工程组复盘：权限切换前由业务负责人确认访问清单，保留旧配置以便回退；知识库发布后继续收集未命中问题，避免把发布完成等同于检索效果已经全面改善。\n"
    "业务应用组复盘：告警规则变更增加运行交接检查；移动审批涉及终端兼容差异，后续仍需积累使用反馈。没有提供效率提升前后对照，不写缩短处理时长或节省成本结论。\n"
    "风险登记SYN-P007：资产门户等待上游资产字段确认，主体功能已进入验收准备；未形成正式验收意见前，项目仍按进行中登记。\n"
    "风险登记SYN-P008：主数据质量规则仍存在历史字段口径争议，由数据工程组组织业务方确认例外规则，未提供缺陷率基线，不推断质量提升比例。\n"
    "风险登记SYN-P009：备份恢复演练的跨环境验收清单尚未签认，先补齐恢复步骤证据，再安排业务负责人复核；不据此宣称已经满足灾备目标。\n"
    "风险登记SYN-P010：预生产环境权限审批尚未完成，发布流水线改造处于暂停；质量运维组负责协调环境授权，授权完成后再恢复联调排期。\n"
    "风险登记SYN-P011：日志脱敏需要新增业务字段样例，先补齐字段分类和抽查规则，避免在材料不足时把规则覆盖范围写成全量。\n"
    "风险登记SYN-P012：历史档案存在多种命名方式，先确认分类规范再批量建立索引，当前阶段成果不能替代整体上线验收。\n"
    "考勤说明：人员编号是匿名模拟编号；实际工时超过计划的部分单列，不提高出勤率；请假和缺勤不扣除计划工时分母；迟到分钟已反映在当日实际工时内，不再次扣减。\n"
    "后续计划：优先推进资产门户验收和主数据口径确认；同步补齐恢复演练证据、解除流水线环境依赖，再按台账计划推进日志脱敏和档案索引。\n"
    "报告边界：缺少预算、收入、成本、客户收益与历史同期数据，不能编造这些指标，也不能把排班数据中的超计划工时等同于经审批的加班时长。\n"
)
ADMIN_NOTES = (
    "虚构案例：衡川数智行政部服务工作记录。所有服务单、反馈、人员编号均为合成数据，不代表真实用户意见。\n"
    "范围：行政部；开始日2026-01-01，结束日2026-04-01（不含结束日）；反馈发生日决定统计期间；量表均为1至5分，分数越高表示满意程度越高。\n"
    "服务范围：会议支持、物业报修、办公用品、差旅支持、入离职支持和档案借阅；服务单编号可用于核查业务关联，不应把反馈条数当作全部服务单总量。\n"
    "样本口径：同一量表的有效反馈可汇总；valid=false记录分别标注重复提交、场景不符、主动撤回和内部测试原因；保留原始评分以便审计，统计时剔除。\n"
    "反馈说明：提交者编号仅用于模拟匿名反馈来源，不是实名；样本没有部门全体员工名单或随机抽样设计，不能声称代表所有员工意见。\n"
    "会议支持复盘：反馈集中在设备联调、会议室临时调整和材料摆放；已将会前检查单与现场交接纳入常规工作，下一阶段继续收集故障场景。\n"
    "物业报修复盘：部分反馈提到进场时间沟通不足；行政接口人统一向申请人反馈受理、预约和完成状态，尚无完整时效日志，不计算响应时长或按时办结率。\n"
    "办公用品复盘：缺货和替代品说明容易形成理解偏差；采购联络人先确认可替代型号，再由申请方确认领取安排，不编造采购节约金额。\n"
    "差旅支持复盘：申请材料不完整时先返回缺失清单；未提供票价和报销数据，不推断差旅成本下降。\n"
    "入离职支持复盘：行政与信息技术接口需同步设备、工位和门禁清单；本例只提供满意度反馈，不把这些记录改写成完整入离职总人数。\n"
    "档案借阅复盘：借阅规则和归还提醒保持一致，后续补充档案类别说明；不依据评价文字推导遗失率或归还及时率。\n"
    "后续计划：持续优化报修状态沟通与会议设备检查，复核无效反馈处理依据，保留原始服务记录；月度样本差异仅作描述，不归因于单一整改措施。\n"
    "报告边界：缺少去年同期、服务总单量、人员考勤和项目台账；本案例适合满意度与服务改进汇报，不应要求系统编造项目或考勤指标。\n"
)


def weekdays(start, end):
    """Explicit fictional company calendar: weekdays, without holiday adjustments."""
    current, days = date.fromisoformat(start), []
    while current < date.fromisoformat(end):
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def event(*parts):
    return hashlib.sha256("|".join((SEED, *map(str, parts))).encode()).digest()


def csv_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def project_rows():
    rows = []
    for index, (name, progress, completed, due) in enumerate(PROJECTS, 1):
        for month, snapshot in enumerate(("2026-04-30", "2026-05-31", "2026-06-30")):
            is_complete = bool(completed and completed <= snapshot)
            rows.append(
                dict(
                    project_id=f"SYN-P{index:03}",
                    department="技术部",
                    effective_date="2026-03-02",
                    snapshot_date=snapshot,
                    status="completed"
                    if is_complete
                    else ("paused" if index == 10 and month == 2 else "in_progress"),
                    progress=progress[month],
                    completed_date=completed if is_complete else "",
                    project_name=name,
                    owner_id=f"SYN-U{index * 2 - 1:03}",
                    team=TEAMS[(index - 1) // 3],
                    planned_due_date=due,
                    risk_level="中" if index in {7, 8, 9, 10} and not is_complete else "低",
                )
            )
    return rows


def attendance_rows():
    rows = []
    for day in weekdays("2026-04-01", "2026-07-01"):
        for person in range(1, 25):
            identifier = f"SYN-U{person:03}"
            digest = event("attendance", identifier, day)
            bucket = int.from_bytes(digest[:2], "big") % 1000
            actual, leave, absent, late = 8, 0, 0, 0
            status, leave_type, note = "正常", "", "日常项目实施与运行交接"
            if bucket < 6:
                actual, absent, status, note = 0, 8, "缺勤", "待补充缺勤说明"
            elif bucket < 80:
                leave = 8 if bucket < 25 else 4 if bucket < 55 else 2
                actual, status = 8 - leave, "请假"
                leave_type = ("病假", "事假", "调休")[digest[2] % 3]
                note = "按模拟审批记录登记请假"
            elif bucket < 130:
                late = 15 if bucket < 110 else 30
                actual, status, note = 8 - late / 60, "迟到", "迟到时长已体现在实际工时"
            elif bucket < 250:
                actual, status = 9 + digest[2] % 2, "超计划"
                note = ("版本发布支持", "故障恢复演练", "联调问题复核")[digest[3] % 3]
            rows.append(
                dict(
                    person_id=identifier,
                    department="技术部",
                    date=day,
                    planned_hours=8,
                    actual_hours=f"{actual:g}",
                    leave_hours=leave,
                    absent_hours=absent,
                    late_minutes=late,
                    team=TEAMS[(person - 1) // 6],
                    role="项目负责人" if person % 2 else "实施工程师",
                    project_id=f"SYN-P{(person + 1) // 2:03}",
                    attendance_status=status,
                    leave_type=leave_type,
                    work_note=note,
                )
            )
    return rows


def achievement_rows():
    rows = []
    for index, (name, _, completed, _) in enumerate(PROJECTS, 1):
        for month, day, category, suffix in (
            (4, 8 + index, "技术文档", "接口与业务边界说明评审"),
            (5, 6 + index, "质量改进", "边界场景回归用例完善"),
            (6, 3 + index, "运维优化", "运行交接与问题定位手册整理"),
        ):
            rows.append(
                dict(
                    department="技术部",
                    date=f"2026-{month:02}-{day:02}",
                    category=category,
                    name=f"{name}：{suffix}",
                    project_id=f"SYN-P{index:03}",
                    owner_id=f"SYN-U{index * 2 - 1:03}",
                    evidence=f"SYN-EVID-P{index:03}-{month:02}",
                )
            )
        if completed:
            rows.append(
                dict(
                    department="技术部",
                    date=completed,
                    category="项目交付",
                    name=f"{name}：业务验收与交付交接",
                    project_id=f"SYN-P{index:03}",
                    owner_id=f"SYN-U{index * 2 - 1:03}",
                    evidence=f"SYN-EVID-P{index:03}-ACCEPT",
                )
            )
    return [
        dict(achievement_id=f"SYN-A{index:03}", **row)
        for index, row in enumerate(sorted(rows, key=lambda row: (row["date"], row["name"])), 1)
    ]


def feedback_rows():
    rows = []
    reasons = {7: "重复提交", 23: "评价场景不符", 41: "提交者主动撤回", 65: "内部测试"}
    for month, counts in enumerate(SERVICE_COUNTS, 1):
        end = f"2026-{month + 1:02}-01"
        days = weekdays(f"2026-{month:02}-01", end)
        services = [
            service
            for service, count in zip(SERVICE_TYPES, counts, strict=True)
            for _ in range(count)
        ]
        # Deterministic service allocation; final records are sorted by feedback date.
        services.sort(key=lambda service: (event("service-order", month, service).hex(), service))
        # Repeated types still have an individual sequence, date, requester, and service ticket.
        for index, service in enumerate(services):
            day = days[(index * 3 + month) % len(days)]
            digest = event("feedback", month, index, service)
            bucket = int.from_bytes(digest[:2], "big") % 100
            thresholds = ((28, 74, 91, 98), (32, 80, 94, 99), (40, 88, 97, 100))[month - 1]
            score = next((5 - rank for rank, limit in enumerate(thresholds) if bucket < limit), 1)
            if service == "物业报修" and digest[2] % 5 == 0:
                score = max(1, score - 1)
            reason = reasons.get(index, "")
            ticket = f"SYN-T{month:02}{index + 1:03}"
            if reason == "重复提交":
                ticket = f"SYN-T{month:02}{index:03}"
            comment = (
                "过程沟通清楚，服务符合预期"
                if score >= 4
                else "基本完成需求，交接说明仍可完善"
                if score == 3
                else "进度信息不够明确，希望主动告知后续安排"
            )
            rows.append(
                dict(
                    feedback_id=f"SYN-F{month:02}{index + 1:03}",
                    department="行政部",
                    date=day,
                    score=score,
                    scale_min=1,
                    scale_max=5,
                    valid="false" if reason else "true",
                    service_type=service,
                    ticket_id=ticket,
                    requester_id=f"SYN-R{1 + (index * 7 + month) % 48:03}",
                    channel=("服务门户", "企业消息", "现场服务")[digest[3] % 3],
                    resolution_status="已完成",
                    comment=comment,
                    invalid_reason=reason,
                )
            )
    return sorted(rows, key=lambda row: (row["date"], row["feedback_id"]))


def generate(output):
    output = Path(output)
    projects, attendance = project_rows(), attendance_rows()
    achievements, feedback = achievement_rows(), feedback_rows()
    files = {
        "technical-q2/项目进度.csv": csv_bytes(projects),
        "technical-q2/人员考勤.csv": csv_bytes(attendance),
        "technical-q2/成果统计.csv": csv_bytes(achievements),
        "technical-q2/工作说明.txt": TECH_NOTES.encode("utf-8"),
        "administration-q1/满意度.csv": csv_bytes(feedback),
        "administration-q1/服务说明.txt": ADMIN_NOTES.encode("utf-8"),
    }
    valid = [row for row in feedback if row["valid"] == "true"]
    planned = sum(float(row["planned_hours"]) for row in attendance)
    actual = sum(float(row["actual_hours"]) for row in attendance)
    credited = sum(min(8, float(row["actual_hours"])) for row in attendance)
    manifest = dict(
        schema_version=1,
        seed=SEED,
        fictional=True,
        statement="全部数据为确定性虚构案例，不含真实企业、人员、服务或经营信息。",
        algorithm=(
            "SHA-256(seed|event_kind|stable_ids); see generate.py; no random() or current time"
        ),
        files={
            name: dict(sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data))
            for name, data in files.items()
        },
        technical_q2=dict(
            department="技术部",
            start_date="2026-04-01",
            end_date="2026-07-01",
            attendance_scope=dict(
                calendar="虚构企业周一至周五排班，不按法定节假日及调休调整",
                roster=[f"SYN-U{index:03}" for index in range(1, 25)],
                work_dates=weekdays("2026-04-01", "2026-07-01"),
            ),
            expected=dict(
                project_snapshot_rows=len(projects),
                project_count=12,
                completed_project_count=6,
                completed_in_period=6,
                completion_rate=0.5,
                attendance_people=24,
                attendance_work_dates=65,
                attendance_rows=len(attendance),
                attendance_rows_by_month=dict(Counter(row["date"][:7] for row in attendance)),
                attendance_status_counts=dict(
                    Counter(row["attendance_status"] for row in attendance)
                ),
                sample_planned_hours=planned,
                sample_actual_hours=actual,
                sample_credited_hours=credited,
                sample_excess_hours=actual - credited,
                sample_leave_hours=sum(row["leave_hours"] for row in attendance),
                absent_hours=sum(row["absent_hours"] for row in attendance),
                late_minutes=sum(row["late_minutes"] for row in attendance),
                sample_attendance_rate=credited / planned,
                declared_scope_attendance_coverage=1.0,
                declared_scope_attendance_rate=credited / planned,
                achievement_count=len(achievements),
                achievement_category_counts=dict(Counter(row["category"] for row in achievements)),
                achievement_rows_by_month=dict(Counter(row["date"][:7] for row in achievements)),
            ),
        ),
        administration_q1=dict(
            department="行政部",
            start_date="2026-01-01",
            end_date="2026-04-01",
            expected=dict(
                feedback_rows=len(feedback),
                valid_feedback_rows=len(valid),
                invalid_feedback_rows=len(feedback) - len(valid),
                score_sum=sum(row["score"] for row in valid),
                satisfaction_mean=sum(row["score"] for row in valid) / len(valid),
                all_feedback_score_histogram=dict(
                    sorted(Counter(row["score"] for row in feedback).items())
                ),
                valid_feedback_score_histogram=dict(
                    sorted(Counter(row["score"] for row in valid).items())
                ),
                feedback_by_month={
                    f"2026-{month:02}": dict(
                        rows=sum(row["date"].startswith(f"2026-{month:02}") for row in feedback),
                        valid_rows=sum(row["date"].startswith(f"2026-{month:02}") for row in valid),
                        valid_score_sum=sum(
                            row["score"]
                            for row in valid
                            if row["date"].startswith(f"2026-{month:02}")
                        ),
                    )
                    for month in range(1, 4)
                },
                service_type_counts=dict(Counter(row["service_type"] for row in feedback)),
                invalid_reason_counts=dict(
                    Counter(row["invalid_reason"] for row in feedback if row["invalid_reason"])
                ),
            ),
        ),
    )
    for name, data in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    arguments = parser.parse_args()
    result = generate(arguments.output)
    print(
        json.dumps(
            {key: result[key]["expected"] for key in ("technical_q2", "administration_q1")},
            ensure_ascii=False,
            indent=2,
        )
    )
