import unittest

from src.services.phi_scrubber import PHIScrubber


class TestPHIScrubber(unittest.TestCase):
    def setUp(self) -> None:
        self.scrubber = PHIScrubber()

    def test_scrubs_name(self) -> None:
        result = self.scrubber.scrub("Patient Jane Doe reports fatigue.")

        self.assertIn("[PHI_NAME_001]", result.sanitized_text)
        self.assertNotIn("Jane Doe", result.sanitized_text)
        self.assertEqual(result.token_map["[PHI_NAME_001]"], "Jane Doe")
        self.assertEqual(result.entity_types, ["NAME"])

    def test_scrubs_email(self) -> None:
        result = self.scrubber.scrub("Contact patient at jane.doe@example.org.")

        self.assertIn("[PHI_EMAIL_001]", result.sanitized_text)
        self.assertNotIn("jane.doe@example.org", result.sanitized_text)
        self.assertEqual(result.token_map["[PHI_EMAIL_001]"], "jane.doe@example.org")

    def test_scrubs_phone_number(self) -> None:
        result = self.scrubber.scrub("Callback number is (415) 555-0188.")

        self.assertIn("[PHI_PHONE_001]", result.sanitized_text)
        self.assertNotIn("(415) 555-0188", result.sanitized_text)
        self.assertEqual(result.token_map["[PHI_PHONE_001]"], "(415) 555-0188")

    def test_scrubs_mrn_like_id(self) -> None:
        result = self.scrubber.scrub("MRN: 4821901 should not leave the control plane.")

        self.assertIn("[PHI_MRN_001]", result.sanitized_text)
        self.assertNotIn("4821901", result.sanitized_text)
        self.assertEqual(result.token_map["[PHI_MRN_001]"], "4821901")

    def test_scrubs_insurance_like_id(self) -> None:
        result = self.scrubber.scrub("Insurance ID: INS-44556677 is active.")

        self.assertIn("[PHI_INSURANCE_ID_001]", result.sanitized_text)
        self.assertNotIn("INS-44556677", result.sanitized_text)
        self.assertEqual(result.token_map["[PHI_INSURANCE_ID_001]"], "INS-44556677")

    def test_returns_entity_count_and_types_for_multiple_phi_values(self) -> None:
        result = self.scrubber.scrub(
            "Patient Jane Doe, MRN 4821901, phone 415-555-0188, "
            "email jane.doe@example.org, Insurance ID INS-44556677."
        )

        self.assertEqual(result.entity_count, 5)
        self.assertEqual(
            result.entity_types,
            ["NAME", "MRN", "PHONE", "EMAIL", "INSURANCE_ID"],
        )
        self.assertEqual(len(result.token_map), 5)

    def test_raw_phi_is_removed_from_sanitized_text(self) -> None:
        raw_values = [
            "Jane Doe",
            "jane.doe@example.org",
            "415-555-0188",
            "4821901",
            "INS-44556677",
        ]
        text = (
            "Patient Jane Doe can be reached at jane.doe@example.org or "
            "415-555-0188. MRN 4821901. Insurance ID INS-44556677."
        )

        result = self.scrubber.scrub(text)

        for raw_value in raw_values:
            self.assertNotIn(raw_value, result.sanitized_text)


if __name__ == "__main__":
    unittest.main()
