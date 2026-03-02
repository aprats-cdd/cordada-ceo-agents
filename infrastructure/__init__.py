"""
Infrastructure layer — external service adapters and tool implementations.

This package contains the anti-corruption layer between external services
(Google APIs, Slack SDK, Anthropic proxy) and the orchestrator/domain layers.

Follows hexagonal architecture: dependencies flow inward.
    infrastructure → orchestrator → domain
"""
