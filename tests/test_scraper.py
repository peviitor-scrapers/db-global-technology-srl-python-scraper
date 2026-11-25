"""Unit tests for the DB Global Technology scraper (stdlib unittest only)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scraper  # noqa: E402


class UrlTests(unittest.TestCase):
    def test_build_job_url(self):
        self.assertEqual(
            scraper.build_job_url("/job/Bucharest-6A-Dimitrie-Pompeiu-Blvd/AI-Engineer_R0459186"),
            "https://db.wd3.myworkdayjobs.com/DBWebsite/job/"
            "Bucharest-6A-Dimitrie-Pompeiu-Blvd/AI-Engineer_R0459186",
        )

    def test_reject_bad_paths_and_tracking(self):
        self.assertIsNone(scraper.build_job_url(""))
        self.assertIsNone(scraper.build_job_url("/search"))  # generic page, not a job
        self.assertIsNone(scraper.build_job_url("https://evil.example/job/1"))
        self.assertIsNone(
            scraper.build_job_url("/job/Bucharest/Dev_R1?utm_source=peviitor")
        )

    def test_clean_title(self):
        self.assertEqual(scraper.clean_title("  Senior&nbsp; Java   Developer "), "Senior Java Developer")
        self.assertEqual(scraper.clean_title("N/A"), "")
        self.assertEqual(scraper.clean_title("-"), "")
        self.assertEqual(scraper.clean_title("a"), "")


class MappingTests(unittest.TestCase):
    def test_build_peviitor_job(self):
        job = scraper.build_peviitor_job(
            {
                "title": "AI Engineer (f/m/x)",
                "url": "https://db.wd3.myworkdayjobs.com/DBWebsite/job/Bucharest/AIEngineer_R1",
                "location": "Bucharest, 6A Dimitrie Pompeiu Blvd",
            },
            "2026-11-25T10:00:00Z",
        )
        self.assertEqual(job["company"], "DB GLOBAL TECHNOLOGY SRL")
        self.assertEqual(job["cif"], "32193007")
        self.assertEqual(job["location"], ["București"])
        self.assertEqual(job["status"], "scraped")
        self.assertEqual(job["date"], "2026-11-25T10:00:00Z")

    def test_no_location_when_not_bucharest(self):
        job = scraper.build_peviitor_job(
            {"title": "Developer", "url": "https://db.wd3.myworkdayjobs.com/DBWebsite/job/X/Dev_R1", "location": "Pune"},
            "2026-11-25T10:00:00Z",
        )
        self.assertNotIn("location", job)

    def test_build_jobs_deduplicates(self):
        raw = {
            "title": "Developer",
            "url": "https://db.wd3.myworkdayjobs.com/DBWebsite/job/Bucharest/Dev_R1",
            "location": "Bucharest",
        }
        jobs = scraper.build_jobs([raw, dict(raw)])
        self.assertEqual(len(jobs), 1)


class FetchTests(unittest.TestCase):
    def test_fetch_jobs_paginates_and_filters(self):
        page1 = {
            "total": 3,
            "jobPostings": [
                {
                    "title": "AI Engineer",
                    "externalPath": "/job/Bucharest/AI_R1",
                    "locationsText": "Bucharest, 6A Dimitrie Pompeiu Blvd",
                    "bulletFields": ["R1"],
                },
                {
                    "title": "QA Engineer",
                    "externalPath": "/job/Pune/QA_R2",
                    "locationsText": "Pune - Business Bay",
                    "bulletFields": ["R2"],
                },
            ],
        }
        page2 = {
            "total": 0,
            "jobPostings": [
                {
                    "title": "Java Developer",
                    "externalPath": "/job/Bucharest/Java_R3",
                    "locationsText": "Bucharest Ion Mihalache Blvd",
                    "bulletFields": ["R3"],
                }
            ],
        }
        pages = iter([page1, page2])

        def fake_http_json(method, url, body=None, **kwargs):
            self.assertEqual(method, "POST")
            self.assertEqual(body["appliedFacets"]["Country"], [scraper.ROMANIA_FACET_ID])
            return next(pages)

        with mock.patch.object(scraper, "http_json", side_effect=fake_http_json), mock.patch.object(
            scraper.time, "sleep"
        ):
            jobs = scraper.fetch_jobs(page_size=2, page_delay=0)

        self.assertEqual([job["title"] for job in jobs], ["AI Engineer", "Java Developer"])
        self.assertTrue(all(job["url"].startswith("https://db.wd3.myworkdayjobs.com/DBWebsite/job/") for job in jobs))


if __name__ == "__main__":
    unittest.main()
