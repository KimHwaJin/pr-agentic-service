"""API use cases that span several tables or services.

Routers stay HTTP-only (parse, check access, call, shape the response).
Domain services shared with the worker live in ``core``.
"""
