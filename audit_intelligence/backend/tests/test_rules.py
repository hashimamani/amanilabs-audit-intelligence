"""The rule catalogue describes every registered rule and nothing else."""

from app.rules.engine import RULE_REGISTRY


def test_catalogue_covers_every_registered_rule(client, default_token, headers):
    assert client.get("/rules").status_code == 401
    rules = client.get("/rules", headers=headers(default_token)).json()
    assert [r["rule_id"] for r in rules] == [cls.rule_id for cls in RULE_REGISTRY]
    for rule in rules:
        assert rule["rule_name"] and rule["summary"] and rule["detail"] and rule["signal"]
        for t in rule["thresholds"]:
            assert t["label"] != t["key"], f"{rule['rule_id']}: threshold {t['key']} has no plain label"
    r001 = next(r for r in rules if r["rule_id"] == "R001")
    assert {"key": "multiplier", "label": "times the member's average withdrawal", "value": 10} in r001["thresholds"]
