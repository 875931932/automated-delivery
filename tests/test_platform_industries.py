import unittest
from unittest.mock import Mock, patch

import platform_industries


class PlatformIndustryParserTests(unittest.TestCase):
    def test_fetch_uses_industry_endpoint_and_normalizes_payload(self):
        payload = {
            "code": 0,
            "zpData": [
                {
                    "code": 100000,
                    "name": "互联网",
                    "subLevelModelList": [
                        {"code": 100020, "name": "互联网"},
                        {"code": 100021, "name": "电子商务"},
                    ],
                }
            ],
        }
        response = Mock()
        response.json.return_value = payload

        with patch.object(platform_industries.requests, "get", return_value=response) as get:
            result = platform_industries.fetch_platform_industries(timeout=3)

        get.assert_called_once_with(
            "https://www.zhipin.com/wapi/zpCommon/data/industry.json",
            timeout=3,
        )
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(result, [
            {
                "code": "100000",
                "name": "互联网",
                "children": [
                    {"code": "100020", "name": "互联网"},
                    {"code": "100021", "name": "电子商务"},
                ],
            }
        ])

    def test_nonzero_business_code_raises_platform_message(self):
        with self.assertRaisesRegex(ValueError, "IP 地址异常"):
            platform_industries.parse_platform_industries({
                "code": 35,
                "message": "IP 地址异常",
                "zpData": {},
            })

    def test_non_list_zpdata_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "industry"):
            platform_industries.parse_platform_industries({
                "code": 0,
                "zpData": {},
            })

    def test_invalid_and_duplicate_children_are_ignored(self):
        result = platform_industries.parse_platform_industries({
            "code": 0,
            "zpData": [
                {
                    "code": 100000,
                    "name": "互联网",
                    "subLevelModelList": [
                        {"code": 100020, "name": "互联网"},
                        {"code": "100020", "name": "互联网"},
                        {"code": "bad-id", "name": "无效行业"},
                        {"code": 100021, "name": ""},
                        None,
                    ],
                }
            ],
        })

        self.assertEqual(result, [{
            "code": "100000",
            "name": "互联网",
            "children": [{"code": "100020", "name": "互联网"}],
        }])

    def test_parser_does_not_make_network_requests(self):
        with patch.object(platform_industries.requests, "get") as get:
            result = platform_industries.parse_platform_industries({
                "code": 0,
                "zpData": [],
            })

        self.assertEqual(result, [])
        get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
