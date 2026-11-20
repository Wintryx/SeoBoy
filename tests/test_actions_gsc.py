from __future__ import annotations

from types import SimpleNamespace
import unittest

from seoboy.analysis import actions
from seoboy.analysis.audit_data import UrlInfo
from seoboy.analysis.rules import Evidence, _rule


class FakeData:
    def __init__(self, url: str) -> None:
        self.urls = {
            1: UrlInfo(
                url_id=1,
                url=url,
                state="checked",
                reason_code=None,
                page_type="service",
                business_value="high",
                expected_indexable=True,
                click_depth=1,
                admitted_at=None,
            )
        }
        self.config = SimpleNamespace(allowed_hosts=("example.de",))

    def url_string(self, url_id: int) -> str:
        return self.urls[url_id].url


def finding(rule_id: str, query: str, impressions: int, position: float) -> object:
    return _rule(
        rule_id,
        f"subject-{query}",
        "query",
        "page_query",
        "gsc",
        "finding",
        severity="medium",
        confidence="confirmed",
        urls=[(1, "affected")],
        evidence=[
            Evidence(
                source_kind="gsc",
                observed_at="",
                facts={
                    "query": query,
                    "impressions": impressions,
                    "clicks": 0,
                    "position": position,
                },
            )
        ],
        fix_kind="gsc_near_top" if rule_id == "GSC_NEAR_TOP" else "gsc_multi_url",
        group_key=query,
    )


class GscActionTests(unittest.TestCase):
    def test_query_findings_are_bundled_by_page(self):
        data = FakeData("https://example.de/hochzeit-dj/")
        first = finding("GSC_NEAR_TOP", "hochzeits dj nrw", 100, 8.7)
        second = finding("GSC_NEAR_TOP", "hochzeit dj koeln", 53, 9.1)
        groups = actions._bundle_query_findings(
            data,
            {
                ("GSC_NEAR_TOP", "gsc_near_top", "hochzeits dj nrw"): [first],
                ("GSC_NEAR_TOP", "gsc_near_top", "hochzeit dj koeln"): [second],
            },
        )
        self.assertEqual(len(groups), 1)
        bundled = next(iter(groups.values()))
        self.assertEqual(len(bundled), 2)
        title, fix, _effect, _verification = actions._texts(
            data, "GSC_NEAR_TOP", "gsc_near_top", bundled, [data.urls[1]]
        )
        self.assertIn("2 Suchanfragen bündeln", title)
        self.assertIn("153 Impressionen", fix)
        self.assertEqual(actions._priority("GSC_NEAR_TOP", "gsc_near_top", bundled, [data.urls[1]], 2), 2)

    def test_multi_url_is_observation(self):
        data = FakeData("https://example.de/hochzeit-dj/")
        item = finding("GSC_MULTI_URL", "hochzeits dj koeln", 150, 9.7)
        title, fix, _effect, _verification = actions._texts(
            data, "GSC_MULTI_URL", "gsc_multi_url", [item], [data.urls[1]]
        )
        self.assertIn("beobachten", title)
        self.assertIn("Positionsdifferenz", fix)
        self.assertEqual(
            actions._priority("GSC_MULTI_URL", "gsc_multi_url", [item], [data.urls[1]], 1),
            4,
        )


if __name__ == "__main__":
    unittest.main()
