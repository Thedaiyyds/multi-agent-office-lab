"""Constrained prose checks close the observed v0.4 unsupported-narrative gap."""

from pathlib import Path

import pytest

from office_agents.agent_examples import sample_content, sample_outline, sample_requirements
from office_agents.agent_schemas import Draft, Review
from office_agents.agents.checker import check_draft, run_checker
from office_agents.agents.writer import allowed_section_texts, render_draft, run_writer
from office_agents.schemas import DataRequest
from office_agents.tools.metrics import run_data_tools

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


class RecordingSession:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def json(self, role, system, user, output_model, *, max_output_tokens):
        self.calls.append((role, user, max_output_tokens))
        return output_model.model_validate(self.output)


@pytest.fixture
def grounded_inputs():
    requirements = sample_requirements()
    outline = sample_outline(requirements)
    data = run_data_tools(
        SAMPLES,
        DataRequest.model_validate(
            requirements.model_dump(exclude={"required_sections", "output_format"})
        ),
    )
    content = sample_content(outline, data)
    allowed = allowed_section_texts(outline)
    for section in content.sections:
        section.text = allowed[section.section_id]
    draft = Draft(**content.model_dump(), markdown=render_draft(content))
    return requirements, outline, data, draft


def refresh(draft):
    draft.markdown = render_draft(draft)


def test_normal_constrained_report_copies_allowed_text_and_preserves_facts(grounded_inputs):
    requirements, outline, data, draft = grounded_inputs
    original = data.model_dump_json()
    writer = RecordingSession(draft.model_dump(exclude={"markdown"}))
    actual = run_writer(requirements, outline, data, writer, strict_narrative=True)
    assert writer.calls[0][1]["allowed_section_texts"] == allowed_section_texts(outline)
    assert writer.calls[0][1]["previous_draft"] is None
    assert writer.calls[0][1]["review"] is None
    assert actual == draft
    assert check_draft(requirements, outline, data, draft, strict_narrative=True) == []
    session = RecordingSession(Review(passed=True))
    review = run_checker(
        requirements,
        outline,
        data,
        draft,
        session,
        strict_narrative=True,
        skip_model_on_local_errors=True,
    )
    assert review.passed and len(session.calls) == 1
    assert session.calls[0][1]["strict_narrative"] is True
    assert "建议（尚未实施）" in actual.markdown and "待人工评估" in actual.markdown
    assert data.model_dump_json() == original


@pytest.mark.parametrize(
    "text",
    ["本期项目数为99。", "部分项目资源分配紧张。", "整体工作按计划推进。", "本章仅报告统计事实。"],
)
@pytest.mark.parametrize("skip_model", [False, True])
def test_unapproved_prose_rejected_even_if_model_approves(grounded_inputs, text, skip_model):
    requirements, outline, data, draft = grounded_inputs
    draft.sections[0].text = text
    refresh(draft)
    session = RecordingSession(Review(passed=True))
    review = run_checker(
        requirements,
        outline,
        data,
        draft,
        session,
        strict_narrative=True,
        skip_model_on_local_errors=skip_model,
    )
    assert not review.passed and not review.needs_input
    assert "unapproved_narrative" in {issue.code for issue in review.issues}
    assert len(session.calls) == (0 if skip_model else 1)
    if skip_model:
        assert any("allowed_section_texts" in item for item in review.revision_instructions)


def test_writer_preserves_invalid_model_text_for_checker(grounded_inputs):
    requirements, outline, data, draft = grounded_inputs
    draft.sections[2].text = "本期资源紧张。"
    content = draft.model_dump(exclude={"markdown"})
    actual = run_writer(
        requirements, outline, data, RecordingSession(content), strict_narrative=True
    )
    assert actual.sections[2].text == "本期资源紧张。"
    assert "unapproved_narrative" in {
        issue.code
        for issue in check_draft(requirements, outline, data, actual, strict_narrative=True)
    }


@pytest.mark.parametrize(
    "change,code",
    [
        ("unit", "fact_unit"),
        ("source", "fact_sources"),
        ("scope", "issue_scope"),
        ("unknown", "suggestion_section"),
    ],
)
def test_strict_scope_unit_source_and_unknown_section_remain_protected(
    grounded_inputs, change, code
):
    requirements, outline, data, draft = grounded_inputs
    if change == "unit":
        draft.fact_claims[0].unit = "ratio"
    elif change == "source":
        draft.fact_claims[0].source_ids = ["untrusted.csv"]
    elif change == "scope":
        draft.issue_scope = "filtered"
    else:
        draft.suggestions[0].section_id = "unknown"
    refresh(draft)
    session = RecordingSession(Review(passed=True))
    review = run_checker(
        requirements,
        outline,
        data,
        draft,
        session,
        strict_narrative=True,
        skip_model_on_local_errors=True,
    )
    assert not review.passed and code in {issue.code for issue in review.issues}
    assert session.calls == []


def test_mismatched_authoritative_input_requests_input_without_model(grounded_inputs):
    requirements, outline, data, draft = grounded_inputs
    data.request.department = "其他部"
    session = RecordingSession(Review(passed=True))
    review = run_checker(
        requirements,
        outline,
        data,
        draft,
        session,
        strict_narrative=True,
        skip_model_on_local_errors=True,
    )
    assert review.needs_input and not review.passed and session.calls == []


def test_freeform_independent_examples_remain_opt_in_compatible(grounded_inputs):
    requirements, outline, data, draft = grounded_inputs
    draft.sections[0].text = "以登记记录为准。"
    refresh(draft)
    assert check_draft(requirements, outline, data, draft) == []
    assert check_draft(requirements, outline, data, draft, strict_narrative=True)
