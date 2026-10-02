"""Concept layer: synthetic chart entries only. No real data."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from clinic_review.concepts import ConceptLayer, Observation, ValueSetError, parse_valueset
from clinic_review.concepts.__main__ import check, main as concepts_main
from clinic_review.concepts.text import normalize
from clinic_review.engine import SOURCES, Patient, State, evaluate, load_rules

ROOT = Path(__file__).resolve().parent.parent
LAYER = ConceptLayer.load(ROOT / "valuesets")
RULES = load_rules(ROOT / "rules")
AS_OF = date(2026, 10, 2)


def concepts(source: str, *, text=None, code=None) -> set[str]:
    return {f.concept for f in LAYER.resolve(Observation(source, "o1", AS_OF, code=code, text=text)).facts}


def reasons(source: str, text: str) -> list[str]:
    return [s.reason for s in LAYER.resolve(Observation(source, "o1", AS_OF, text=text)).skipped]


# --- the files themselves ------------------------------------------------------------


def test_every_rule_concept_is_defined_and_files_are_current():
    assert check(LAYER, RULES, AS_OF) == []
    assert concepts_main(["check", "--valuesets", str(ROOT / "valuesets"), "--rules", str(ROOT / "rules"), "--today", "2026-10-02"]) == 0


def test_check_catches_an_undefined_concept_and_a_stale_file():
    layer = ConceptLayer([v for v in LAYER.valuesets if v.name != "documents"])
    problems = check(layer, RULES, date(2027, 10, 2))
    assert "dm.eye: reads exam.retinal, which no value set defines" in problems
    assert any(p.startswith("valuesets/conditions.yaml: past its review_by") for p in problems)


def _conditions() -> dict:
    return yaml.safe_load((ROOT / "valuesets" / "conditions.yaml").read_text())


@pytest.mark.parametrize(
    "change, message",
    [
        ({"blocked_by": [False]}, "must be a quoted string"),  # what an unquoted `no` loads as
        ({"concepts": {"dx.x": {"label": "x", "icd9": [42]}}}, "must be a quoted string"),
        ({"concepts": {"dx.x": {"label": "x", "icd9": ["250.01"]}}}, "3 or 4 characters"),
        ({"concepts": {"dx.x": {"label": "x"}}}, "needs icd9 codes, text phrases, or both"),
        ({"concepts": {"Diabetes": {"label": "x", "text": ["dm"]}}}, "isn't a concept name"),
        ({"applies_to": ["chart"]}, "isn't an evidence source"),
        ({"exclusive": [["dx.diabetes", "dx.nope"]]}, "aren't defined in this file"),
        ({"status": "signed"}, "signed_off"),
        ({"extra": 1}, "unknown key"),
    ],
)
def test_bad_value_sets_are_rejected(change, message):
    with pytest.raises(ValueSetError, match=message):
        parse_valueset({**_conditions(), **change})


def test_a_concept_can_only_be_defined_once():
    with pytest.raises(ValueSetError, match="defined in both"):
        ConceptLayer([LAYER.valuesets[0], LAYER.valuesets[0]])


def test_normalize():
    assert normalize("TAH-BSO (2009)") == "tah bso 2009"
    assert normalize("?DM") == "query dm"
    assert normalize("Crohn's") == "crohn s"


# --- MSP codes -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "code, expected",
    [
        ("250", {"dx.diabetes"}),
        ("250.0", {"dx.diabetes"}),
        ("2504", {"dx.diabetes"}),
        ("401.9", {"dx.hypertension"}),
        ("042", {"dx.hiv"}),
        ("1541", {"dx.colorectal_cancer"}),  # rectum
        ("1542", set()),  # anal canal isn't colorectal
        ("V45.1", {"proc.dialysis"}),
        ("V425", set()),  # a corneal graft doesn't make someone immunocompromised
        ("V420", {"dx.organ_transplant"}),
        ("2794", set()),  # autoimmune disease NEC isn't immunodeficiency
        ("30B", {"state.pregnancy"}),
        ("36B", set()),  # pregnancy unconfirmed
    ],
)
def test_msp_codes(code, expected):
    assert concepts("encounters", code=code) == expected


# --- condition text ------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Type 2 diabetes", {"dx.diabetes"}),
        ("DM2 - no retinopathy", {"dx.diabetes"}),  # "no" after the match doesn't negate it
        ("Pre-diabetes", set()),
        ("Gestational diabetes 2019", set()),
        ("Diabetes insipidus", set()),
        ("?DM", set()),
        ("r/o diabetes", set()),
        ("no DM", set()),
        ("Mother: breast cancer", set()),
        ("Family history of colon cancer", set()),
        ("Colon cancer screening up to date", set()),
        ("Hx of breast cancer, no evidence of recurrence", {"dx.breast_cancer"}),
        ("DCIS left breast 2015", {"dx.breast_cancer"}),
        ("LCIS", set()),
        ("HIV negative", set()),
        ("HIV PrEP", set()),
        ("Hearing aids", set()),
        ("Crohn's disease", {"dx.ibd"}),
        ("CKD stage 4", {"dx.ckd", "dx.ckd_severe"}),  # a refinement keeps its parent
        ("Pulmonary hypertension", set()),
        ("Kidney donor 2012", set()),
        ("CIN 3, LEEP 2018", {"hx.cin2_plus_or_ais"}),
    ],
)
def test_condition_text(text, expected):
    assert concepts("history.medical", text=text) == expected


def test_family_history_screen_never_feeds_conditions():
    assert concepts("history.family", text="Colon cancer") == set()


def test_skip_reasons_quote_value_set_phrases_only():
    assert reasons("history.medical", "Mother: breast cancer") == ["conditions: blocked by 'mother'"]
    assert reasons("history.medical", "no DM") == ["dx.diabetes: 'no' before 'dm'"]
    assert reasons("history.medical", "Pre-diabetes") == ["dx.diabetes: not counted because of 'pre diabetes'"]
    assert reasons("history.medical", "Seasonal allergies") == ["no concept matched"]


# --- procedures and smoking ----------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("TAH-BSO 2009", {"proc.hysterectomy_total"}),
        ("Total hysterectomy for fibroids", {"proc.hysterectomy_total"}),
        ("Supracervical hysterectomy", {"proc.hysterectomy_subtotal"}),
        ("Sub-total hysterectomy", {"proc.hysterectomy_subtotal"}),
        ("Hysterectomy", {"proc.hysterectomy_unspecified"}),
        ("Partial hysterectomy", {"proc.hysterectomy_unspecified"}),
        ("Referred for hysterectomy", set()),
        ("Right hemicolectomy", {"proc.colectomy_partial"}),
        ("Sub-total colectomy", {"proc.colectomy_partial"}),
        ("Total proctocolectomy with J pouch", {"proc.colectomy_total"}),
        ("Bilateral mastectomy 2020", {"proc.mastectomy_bilateral"}),
        ("Breast implants removed 2021", set()),
        ("Anterior vaginoplasty", set()),
    ],
)
def test_procedures(text, expected):
    assert concepts("history.surgical", text=text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Current smoker, 1 ppd", {"risk.current_smoker"}),
        ("Ex-smoker", {"risk.former_smoker"}),
        ("Quit smoking 2015", {"risk.former_smoker"}),
        ("Never smoker", {"risk.never_smoker"}),
        ("Non-smoker", {"risk.not_current_smoker"}),
        ("Lifelong non-smoker", {"risk.never_smoker"}),
        ("Smoker x 20 yrs, quit 2010", set()),  # not current, and nothing says former
        ("Former smoker, now smokes again", set()),  # conflicting, so asked rather than guessed
        ("Partner smokes", set()),
    ],
)
def test_smoking_status(text, expected):
    assert concepts("risk_factors", text=text) == expected


# --- medications ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Atorvastatin 20 mg PO daily", {"rx.statin"}),
        ("Humira 40 mg SC q2w", {"rx.immunosuppressant"}),
        ("Methotrexate 15 mg weekly, hold if infection", {"rx.immunosuppressant"}),
        ("Cyclosporine 0.05% eye drops", set()),
        ("Hydrocortisone 1% cream", set()),
        ("Prednisone 5 mg daily", {"rx.glucocorticoid_systemic"}),
        ("Metformin 500 mg BID", {"rx.metformin"}),
        ("Janumet 50/1000", {"rx.diabetes_specific_noninsulin"}),
        ("Atorvastatin - discontinued, myalgia", set()),
    ],
)
def test_medications(text, expected):
    assert concepts("medications", text=text) == expected


# --- labs ----------------------------------------------------------------------------


def lab(name, result, **kw):
    return LAYER.resolve(Observation("labs", "lab-1", AS_OF, lab_name=name, result=result, **kw))


def test_lab_results_match_exactly():
    r = lab("FIT", "Positive")
    assert [(f.concept, f.value) for f in r.facts] == [("obs.fit", "positive")]
    r = lab("Hemoglobin A1C", "7.2")
    assert [(f.concept, f.value) for f in r.facts] == [("obs.a1c", "7.2")]
    r = lab("HPV", "HPV 16/18 not detected; other HR HPV detected")
    assert [(f.concept, f.value) for f in r.facts] == [("obs.hpv_test", None)]
    assert [s.reason for s in r.skipped] == ["obs.hpv_test: result not in the value set"]


def test_reported_next_due_passes_through():
    due = date(2031, 9, 1)
    [f] = lab("HPV", "Not Detected", next_due=due).facts
    assert (f.value, f.next_due) == ("negative", due)


def test_unknown_lab_name_is_skipped():
    r = lab("Ferritin", "45")
    assert r.facts == () and [s.reason for s in r.skipped] == ["lab name not in any value set"]


# --- documents -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "title, expected",
    [
        ("Screening Mammogram Bilateral", {"imaging.mammogram"}),
        ("Mammogram requisition", set()),  # an order isn't a result
        ("Colonoscopy report", {"proc.colonoscopy"}),
        ("Virtual colonoscopy", {"imaging.ct_colonography"}),
        ("Low-dose CT chest (lung screening)", {"imaging.ldct"}),
        ("Diabetic eye exam - optometry", {"exam.retinal"}),
    ],
)
def test_document_titles(title, expected):
    assert concepts("documents.diagnostic_imaging", text=title) == expected


# --- derived concepts and the whole path ---------------------------------------------


def test_immunosuppressant_in_the_last_two_years_derives_immunocompromised():
    recent = LAYER.facts_for([Observation("medications", "m1", date(2025, 6, 1), text="Methotrexate 15 mg weekly")], AS_OF)
    derived = [f for f in recent.facts if f.concept == "risk.immunocompromised"]
    assert len(derived) == 1 and derived[0].id == "m1" and derived[0].date == date(2025, 6, 1)
    old = LAYER.facts_for([Observation("medications", "m1", date(2024, 6, 1), text="Methotrexate 15 mg weekly")], AS_OF)
    assert "risk.immunocompromised" not in {f.concept for f in old.facts}


def test_chart_rows_to_rule_state():
    """Rows as the fact store would hand them over, through the layer, into the evaluator."""
    diabetes = Observation("history.medical", "pl-1", date(2015, 3, 1), text="Type 2 diabetes")
    eye_exam = Observation("documents.consults", "doc-7", date(2026, 3, 20), text="Diabetic eye exam - optometry")
    tah = Observation("history.surgical", "sx-2", date(2009, 5, 4), text="TAH-BSO")
    humira = Observation("medications", "rx-3", AS_OF, text="Humira 40 mg SC q2w")

    def patient(*rows):
        facts = LAYER.facts_for(rows, AS_OF).facts
        return Patient("p1", date(1968, 4, 2), "F", facts, frozenset(SOURCES))

    eye = evaluate(RULES["dm.eye"], patient(diabetes, eye_exam), AS_OF)
    assert eye.state is State.UP_TO_DATE and eye.evidence_ids == ("doc-7",)
    excluded = evaluate(RULES["cervix.hpv"], patient(tah), AS_OF)
    assert excluded.state is State.EXCLUDED and excluded.evidence_ids == ("sx-2",)
    # On adalimumab, this patient follows the 3-yearly immunocompromised rule instead
    moved = evaluate(RULES["cervix.hpv"], patient(humira), AS_OF)
    assert moved.state is State.NOT_ELIGIBLE and moved.evidence_ids == ("rx-3",)
    assert evaluate(RULES["cervix.hpv"], patient(), AS_OF).state is State.NOT_FOUND
