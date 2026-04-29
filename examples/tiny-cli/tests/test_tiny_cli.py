from tiny_cli import greet


def test_greet():
    assert greet("agent") == "hello, agent"
