from nanoagent.ai import JSONObject, JSONPrimitive, JSONValue


def test_json_aliases_accept_nested_json_like_values():
    primitive: JSONPrimitive = "text"
    value: JSONValue = {"items": [primitive, 1, True, None]}
    obj: JSONObject = {"value": value}

    assert obj["value"] == {"items": ["text", 1, True, None]}
