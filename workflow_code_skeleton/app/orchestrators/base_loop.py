from __future__ import annotations


def should_retry(current_retry_count: int, max_retries: int) -> bool:
    return current_retry_count < max_retries
