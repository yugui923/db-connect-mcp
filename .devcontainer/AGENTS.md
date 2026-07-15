# DevContainer Agent Guide

Whenever any file in this directory changes, review and update [`REQUIREMENTS.md`](REQUIREMENTS.md) in the same change. Keep [`verify-requirements.py`](verify-requirements.py) synchronized with every requirement ID and the effective DevContainer.

Before review, create a disposable DevContainer from the template and run the verifier against it. Every requirement ID must be discovered and pass. Do not add automatic project dependency installation.
