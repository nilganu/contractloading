"""Canonical extraction pipeline.

GPT extracts contracts into a strongly-typed canonical model
(``canonical.ContractExtraction``); deterministic Python in
``moonstride_mapper`` then maps that into Moonstride hotel + supplement
import rows. The LLM never writes Moonstride column names directly —
that mapping (including all conditional rules like Days="1234567" and
Standard/Count/Index blanking) is 100% testable in isolation.
"""
