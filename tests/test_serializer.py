from app.serializer import serialize_locals, serialize_value


def test_object_identity_is_preserved() -> None:
    shared = [1, 2]
    result = serialize_locals({"a": shared, "b": shared, "c": [1, 2]})

    assert result["a"]["object_id"] == result["b"]["object_id"]
    assert result["b"]["type"] == "reference"
    assert result["a"]["object_id"] != result["c"]["object_id"]


def test_circular_reference_does_not_recurse_forever() -> None:
    value: list[object] = []
    value.append(value)

    result = serialize_value(value)

    assert result["items"][0] == {
        "type": "reference",
        "object_id": result["object_id"],
    }

