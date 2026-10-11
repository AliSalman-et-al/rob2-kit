from rob2_kit.application.intake import _document_registry_identifier


def test_own_registration_outranks_cited_trials():
    pages = [
        "A randomized trial. ClinicalTrials.gov number, NCT01234567.",
        "Methods ... as in an earlier trial (NCT07654321).",
        "This trial is registered with ClinicalTrials.gov (NCT01234567).",
    ]
    assert _document_registry_identifier(pages) == "NCT01234567"


def test_tied_registrations_capture_nothing():
    pages = ["Registered at ClinicalTrials.gov: NCT01234567 and NCT07654321."]
    assert _document_registry_identifier(pages) is None


def test_unregistered_report_captures_nothing():
    assert _document_registry_identifier(["No registry is mentioned here."]) is None
