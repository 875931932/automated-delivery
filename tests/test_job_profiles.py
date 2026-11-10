import json
import tempfile
import unittest
from pathlib import Path

from candidate_profiles import CandidateProfile, RoleFamily
from job_profiles import (
    JobProfile,
    JobProfileStore,
    RequirementGroup,
    allocate_query_pages,
    build_unique_queries,
    eligible_profiles,
    load_screening_rules,
    parse_search_keywords,
)


def candidate():
    return CandidateProfile(
        confirmed=True,
        revision=1,
        primary_direction="AI 应用研发",
        allowed_role_families=[RoleFamily(id="backend", name="后端开发")],
    )


def profile(profile_id, keyword, **overrides):
    values = {
        "id": profile_id,
        "name": profile_id,
        "enabled": True,
        "role_family_id": "backend",
        "search_keywords": [keyword],
    }
    values.update(overrides)
    return JobProfile(**values)


class JobProfileModelTests(unittest.TestCase):
    def test_profile_supports_any_alternative_requirement_group(self):
        item = profile(
            "backend",
            "后端开发",
            hard_requirements=[RequirementGroup(
                label="至少掌握一种编程语言",
                options=["C++", "Python", "Java"],
                mode="any",
            )],
        )

        self.assertEqual(item.hard_requirements[0].mode, "any")
        self.assertEqual(item.hard_requirements[0].options, ["C++", "Python", "Java"])

    def test_invalid_threshold_is_rejected_and_empty_search_keywords_are_allowed(self):
        with self.assertRaises(ValueError):
            profile("backend", "后端开发", threshold=101)
        self.assertEqual(profile("recommendations", " ").search_keywords, [])

    def test_only_enabled_profiles_bound_to_confirmed_families_are_eligible(self):
        profiles = [
            profile("enabled", "backend"),
            profile("disabled", "api", enabled=False),
            profile("unbound", "legacy", role_family_id=""),
            profile("outside", "sales", role_family_id="sales"),
        ]

        self.assertEqual([item.id for item in eligible_profiles(profiles, candidate())], ["enabled"])

    def test_profile_diagnostic_terms_are_optional_and_not_skill_weighted(self):
        item = profile("robotics", "机器人软件", diagnostic_terms=["ROS2", "运动控制"])

        self.assertEqual(item.diagnostic_terms, ["ROS2", "运动控制"])
        self.assertEqual(profile("backend", "后端").diagnostic_terms, [])


class JobProfileStoreTests(unittest.TestCase):
    def test_legacy_keyword_creates_disabled_unassigned_draft(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobProfileStore(Path(temp_dir) / "job_profiles.json")

            profiles = store.load_or_migrate("AI应用开发")

            self.assertEqual(profiles[0].search_keywords, ["AI应用开发"])
            self.assertEqual(profiles[0].role_family_id, "")
            self.assertFalse(profiles[0].enabled)
            self.assertEqual(profiles[0].hard_requirements, [])

    def test_existing_profile_file_is_never_augmented_by_legacy_keyword(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "job_profiles.json"
            path.write_text(json.dumps([profile("existing", "后端").model_dump()]), encoding="utf-8")
            before = path.read_bytes()

            profiles = JobProfileStore(path).load_or_migrate("should-not-be-added")

            self.assertEqual([item.id for item in profiles], ["existing"])
            self.assertEqual(path.read_bytes(), before)

    def test_store_round_trips_profiles(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = JobProfileStore(Path(temp_dir) / "job_profiles.json")
            store.save([profile("backend", "后端开发")])

            self.assertEqual(store.load()[0].name, "backend")


class JobProfileQueryTests(unittest.TestCase):
    def test_explicit_alternatives_preserve_phrases_and_merge_duplicates(self):
        self.assertEqual(
            parse_search_keywords(" AI应用开发，Python   API;python api；RAG\nC++/C#开发,AI应用开发 "),
            ["AI应用开发", "Python API", "RAG", "C++/C#开发"],
        )
        self.assertEqual(parse_search_keywords('Python OR Java'), ['Python OR Java'])

    def test_blank_keywords_select_recommendations_but_separators_are_invalid(self):
        self.assertEqual(parse_search_keywords(" \t\r\n"), [])
        with self.assertRaisesRegex(ValueError, "只有分隔符"):
            parse_search_keywords(",，;；\n")

    def test_keyword_limit_counts_unique_normalized_terms(self):
        values = [f"keyword-{index}" for index in range(50)]
        self.assertEqual(parse_search_keywords(";".join(values * 2)), values)
        with self.assertRaisesRegex(ValueError, "不能超过 50"):
            parse_search_keywords(";".join(values + ["extra"]))

    def test_phrase_whitespace_merges_profile_provenance(self):
        self.assertEqual(build_unique_queries([
            profile("one", "Python  API"), profile("two", "python API"),
        ]), [{"keyword": "Python API", "profile_ids": ["one", "two"]}])

    def test_duplicate_keywords_merge_profile_provenance(self):
        profiles = [profile("one", "Python后端"), profile("two", " python后端 ")]

        queries = build_unique_queries(profiles)

        self.assertEqual(queries, [{"keyword": "Python后端", "profile_ids": ["one", "two"]}])

    def test_shared_page_budget_is_distributed_round_robin(self):
        queries = build_unique_queries([profile("one", "后端"), profile("two", "机器人")])

        allocations = allocate_query_pages(queries, page_budget=5)

        self.assertEqual([item["pages"] for item in allocations], [[1, 2, 3], [1, 2]])

    def test_shared_page_budget_must_cover_each_unique_query(self):
        queries = build_unique_queries([profile("one", "后端"), profile("two", "机器人")])

        with self.assertRaises(ValueError):
            allocate_query_pages(queries, page_budget=1)

    def test_screening_rules_must_exist_and_contain_text(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "rules.md"
            with self.assertRaises(ValueError):
                load_screening_rules(path)
            path.write_text("  \n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_screening_rules(path)
            path.write_text("Resume omissions are unverified.", encoding="utf-8")

            self.assertEqual(load_screening_rules(path), "Resume omissions are unverified.")


if __name__ == "__main__":
    unittest.main()
