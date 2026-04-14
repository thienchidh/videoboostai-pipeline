def test_minimax_llm_registered_in_plugin_registry():
    """MiniMaxLLMProvider should be registered under 'llm' category."""
    from core.plugins import get_provider
    from modules.llm.minimax import MiniMaxLLMProvider

    # Verify it's registered
    cls = get_provider("llm", "minimax")
    assert cls is not None, "MiniMaxLLMProvider not registered in plugin registry"
    assert cls is MiniMaxLLMProvider, f"Expected MiniMaxLLMProvider, got {cls}"

    # Verify it can be instantiated
    instance = cls(api_key="fake_key")
    assert hasattr(instance, "chat"), "MiniMaxLLMProvider missing chat() method"