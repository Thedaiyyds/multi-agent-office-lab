"""Independent fixtures verify Writer and Checker without paid API calls."""

from pathlib import Path

import pytest

from office_agents.agent_schemas import (
    Draft,
    DraftContent,
    DraftSection,
    FactClaim,
    Outline,
    OutlineSection,
    Requirements,
    Review,
    ReviewIssue,
    Suggestion,
)
from office_agents.agents.checker import check_draft, run_checker
from office_agents.agents.writer import render_draft, run_writer
from office_agents.llm import ModelCallError
from office_agents.schemas import DataRequest
from office_agents.tools.metrics import run_data_tools

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


class FakeSession:
    def __init__(self, output=None):
        self.output = output
        self.calls = []

    def json(self, role, system, user, output_model, *, max_output_tokens):
        self.calls.append((role, system, user, output_model, max_output_tokens))
        assert self.output is not None, "Unexpected model request"
        return output_model.model_validate(self.output)


@pytest.fixture
def inputs():
    requirements = Requirements(
        department="研发部",
        start_date="2026-04-01",
        end_date="2026-07-01",
        data_origin="simulated",
        required_sections=["工作概况", "主要成果", "问题与风险", "后续计划"],
    )
    outline = Outline(
        sections=[
            OutlineSection(
                section_id="overview",
                title="工作概况",
                purpose="统计项目",
                metric_ids=["project_count", "completed_project_count", "completion_rate"],
            ),
            OutlineSection(
                section_id="results",
                title="主要成果",
                purpose="统计成果",
                metric_ids=["achievement_count"],
            ),
            OutlineSection(section_id="risks", title="问题与风险", purpose="说明范围限制"),
            OutlineSection(section_id="plans", title="后续计划", purpose="提出后续建议"),
        ]
    )
    data = run_data_tools(
        SAMPLES,
        DataRequest(
            department="研发部",
            start_date="2026-04-01",
            end_date="2026-07-01",
            data_origin="simulated",
        ),
    )
    return requirements, outline, data


def valid_content():
    return DraftContent(
        sections=[
            DraftSection(section_id="overview", title="工作概况", text="项目进展以统计记录为准。"),
            DraftSection(section_id="results", title="主要成果", text="成果以登记记录为准。"),
            DraftSection(
                section_id="risks", title="问题与风险", text="问题材料未筛选，不作范围归因。"
            ),
            DraftSection(section_id="plans", title="后续计划", text="继续核对工作进展。"),
        ],
        fact_claims=[
            FactClaim(
                section_id="overview",
                metric_id="project_count",
                value=3,
                unit="count",
                source_ids=["projects.csv"],
            ),
            FactClaim(
                section_id="overview",
                metric_id="completed_project_count",
                value=2,
                unit="count",
                source_ids=["projects.csv"],
            ),
            FactClaim(
                section_id="overview",
                metric_id="completion_rate",
                value=2 / 3,
                unit="ratio",
                source_ids=["projects.csv"],
            ),
            FactClaim(
                section_id="results",
                metric_id="achievement_count",
                value=2,
                unit="count",
                source_ids=["achievements.csv"],
            ),
        ],
        suggestions=[Suggestion(section_id="plans", text="建议复核后续项目状态。")],
    )


def as_draft(content):
    return Draft(**content.model_dump(), markdown=render_draft(content))


def codes(inputs, draft):
    return {issue.code for issue in check_draft(*inputs, draft)}


def test_valid_writer_checker_preserve_authoritative_data(inputs):
    original = inputs[2].model_dump_json()
    writer_session = FakeSession(valid_content())
    draft = run_writer(*inputs, writer_session)
    assert draft.markdown.startswith("# 工作报告草稿")
    assert "完成率 = 0.6666666666666666 [ratio]" in draft.markdown
    assert "建议（尚未实施）" in draft.markdown
    assert "未筛选，不可归因" in draft.markdown
    assert check_draft(*inputs, draft) == []
    checker_session = FakeSession(Review(passed=True))
    assert run_checker(*inputs, draft, checker_session).passed is True
    assert writer_session.calls[0][0] == "writer"
    assert writer_session.calls[0][-1] == 768
    assert checker_session.calls[0][-1] == 256
    assert "issue_materials" not in writer_session.calls[0][2]
    assert inputs[2].model_dump_json() == original


@pytest.mark.parametrize("value", [4, None])
def test_wrong_numeric_facts_rejected_even_when_model_approves(inputs, value):
    content = valid_content()
    content.fact_claims[0].value = value
    draft = run_writer(*inputs, FakeSession(content))
    assert draft.fact_claims[0].value == value or value != value
    review = run_checker(*inputs, draft, FakeSession(Review(passed=True)))
    assert review.passed is False
    assert "fact_value" in {issue.code for issue in review.issues}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400, True])
def test_checker_defends_against_nonfinite_in_memory_mutation(inputs, value):
    draft = as_draft(valid_content())
    if value is True:
        inputs[2].metrics[0].value = 1
    draft.fact_claims[0].value = value
    draft.markdown = render_draft(draft)
    review = run_checker(*inputs, draft, FakeSession(Review(passed=True)))
    assert not review.passed
    assert "fact_value" in {issue.code for issue in review.issues}


@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing", "sections_mismatch"),
        ("duplicate", "duplicate_section"),
        ("title", "required_sections"),
        ("id", "sections_mismatch"),
        ("order", "sections_mismatch"),
    ],
)
def test_required_section_contract(inputs, change, expected):
    content = valid_content()
    if change == "missing":
        content.sections.pop()
    elif change == "duplicate":
        content.sections.append(content.sections[0])
    elif change == "title":
        content.sections[0].title = "错误标题"
    elif change == "id":
        content.sections[0].section_id = "wrong"
    else:
        content.sections.reverse()
    assert expected in codes(inputs, as_draft(content))


@pytest.mark.parametrize(
    "change,expected",
    [
        ("missing", "fact_coverage"),
        ("duplicate", "fact_coverage"),
        ("assignment", "fact_section"),
        ("unit", "fact_unit"),
        ("sources", "fact_sources"),
        ("unknown_section", "suggestion_section"),
    ],
)
def test_fact_and_suggestion_contract(inputs, change, expected):
    content = valid_content()
    if change == "missing":
        content.fact_claims.pop()
    elif change == "duplicate":
        content.fact_claims.append(content.fact_claims[0])
    elif change == "assignment":
        content.fact_claims[0].section_id = "plans"
    elif change == "unit":
        content.fact_claims[0].unit = "ratio"
    elif change == "sources":
        content.fact_claims[0].source_ids = ["unknown.csv"]
    else:
        content.suggestions[0].section_id = "unknown"
    assert expected in codes(inputs, as_draft(content))


def test_edited_markdown_rejected(inputs):
    draft = as_draft(valid_content())
    draft.markdown += "\n项目数99。"
    assert "render_mismatch" in codes(inputs, draft)


def test_render_does_not_allow_model_markdown_to_inject_sections(inputs):
    content = valid_content()
    content.sections[0].text = "普通描述\n## 额外章节\n<script>alert(1)</script>"
    content.suggestions[0].text = "计划\n## 伪造章节"
    draft = as_draft(content)
    assert sum(line.startswith("## ") for line in draft.markdown.splitlines()) == 4
    assert "<script>" not in draft.markdown
    assert check_draft(*inputs, draft) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("department", "市场部"),
        ("start_date", "2026-04-02"),
        ("end_date", "2026-07-02"),
        ("data_origin", "provided"),
    ],
)
def test_mismatched_scope_blocks_writer_and_requires_input(inputs, field, value):
    requirements, outline, data = inputs
    requirements = Requirements.model_validate({**requirements.model_dump(), field: value})
    session = FakeSession()
    with pytest.raises(ModelCallError, match="input contracts"):
        run_writer(requirements, outline, data, session)
    review = run_checker(requirements, outline, data, as_draft(valid_content()), session)
    assert review.needs_input is True
    assert session.calls == []


def test_no_data_gets_explicit_missing_draft_and_no_api(inputs):
    requirements, outline, _ = inputs
    requirements.department = "财务部"
    data = run_data_tools(
        SAMPLES,
        DataRequest(**requirements.model_dump(exclude={"required_sections", "output_format"})),
    )
    session = FakeSession()
    draft = run_writer(requirements, outline, data, session)
    assert draft.fact_claims == []
    assert "无匹配数据" in draft.markdown
    review = run_checker(requirements, outline, data, draft, session)
    assert review.needs_input and not review.passed
    assert {issue.code for issue in review.issues} == {"no_data"}
    assert session.calls == []


def test_invalid_data_blocked_without_api(inputs):
    requirements, outline, data = inputs
    data.status = "invalid_data"
    data.metrics = []
    session = FakeSession()
    with pytest.raises(ModelCallError, match="valid authoritative"):
        run_writer(requirements, outline, data, session)
    assert run_checker(requirements, outline, data, as_draft(valid_content()), session).needs_input
    assert session.calls == []


def test_model_semantic_rejection_preserved(inputs):
    model = Review(
        passed=False,
        issues=[
            ReviewIssue(
                code="unsupported_event", location="sections[0].text", message="正文事件缺少依据。"
            )
        ],
    )
    result = run_checker(*inputs, as_draft(valid_content()), FakeSession(model))
    assert not result.passed
    assert result.issues == model.issues


def test_null_ratio_preserved_for_achievement_only_case(inputs):
    requirements, outline, _ = inputs
    requirements.start_date = requirements.start_date.replace(month=6, day=25)
    requirements.end_date = requirements.end_date.replace(month=6, day=26)
    data = run_data_tools(
        SAMPLES,
        DataRequest(**requirements.model_dump(exclude={"required_sections", "output_format"})),
    )
    content = valid_content()
    for fact, value in zip(content.fact_claims, [0, 0, None, 1], strict=True):
        fact.value = value
    draft = as_draft(content)
    assert "缺失/未定义 [ratio]" in draft.markdown
    assert check_draft(requirements, outline, data, draft) == []


def test_outline_metric_duplication_rejected_before_model(inputs):
    inputs[1].sections[1].metric_ids.append("project_count")
    with pytest.raises(ModelCallError):
        run_writer(*inputs, FakeSession())
    assert "outline_metrics" in codes(inputs, as_draft(valid_content()))


@pytest.mark.parametrize("delta,has_error", [(0.5e-9, False), (2e-9, True)])
def test_ratio_comparison_uses_absolute_tolerance(inputs, delta, has_error):
    content = valid_content()
    content.fact_claims[2].value += delta
    assert ("fact_value" in codes(inputs, as_draft(content))) is has_error


def test_review_issue_cap_retains_local_errors(inputs):
    content = valid_content()
    content.sections = [content.sections[0], content.sections[0]]
    content.fact_claims = [content.fact_claims[0].model_copy(deep=True) for _ in range(8)]
    for fact in content.fact_claims:
        fact.section_id = "unknown"
        fact.value = 99
        fact.unit = "ratio"
        fact.source_ids = ["unknown.csv"]
    content.suggestions = [Suggestion(section_id="unknown", text="建议") for _ in range(6)]
    draft = as_draft(content)
    draft.markdown += "被篡改正文"
    review = run_checker(*inputs, draft, FakeSession(Review(passed=True)))
    assert len(review.issues) == 32
    assert not review.passed
    assert review.issues[0].code == "sections_mismatch"
