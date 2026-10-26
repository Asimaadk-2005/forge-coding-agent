# Recorded negative-fraction regression

`domain.py`, `content.py` and the two rejected responses are copied from the user's
`SpaceFractions_m9n7iqwo` run. The parser drops the sign of a simple fraction, so
`-5/6` becomes `5/6`; the recorded repairs copy the correct caller instead of fixing
the parser. These files are test data and are not supplied to generated games or
included in the portable Forge release.

The offline tests replay the actual rejected responses. Their successful follow-up
response is explicitly authored test data, not a claimed DeepSeek result. Network
and saved-key access are forbidden. The user's original project remains unchanged.
