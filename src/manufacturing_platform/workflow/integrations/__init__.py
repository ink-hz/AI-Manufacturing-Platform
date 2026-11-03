"""Typed OEM integration boundaries; imports never open source storage.

Server composition registers each family on ``routing.SystemRegistry`` with a
source adapter factory, a workflow-transaction projector and a live authorizer.
Legacy-wire facades use the separate ``register_exchange_adapter`` boundary.
No production family is synthesized from catalog metadata.
"""
