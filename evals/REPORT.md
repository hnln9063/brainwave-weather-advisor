# Evaluation results

Executed on 2026-09-17. This report separates deterministic fixture checks, limited demo parsing, actual live weather, and real-model language understanding.

## Results

| Layer | Result | Evidence |
| --- | --- | --- |
| Backend + frontend regression suite | **63 passed** | `pytest-results.xml`; `python -m pytest -q --junitxml=evals/pytest-results.xml` |
| Static checks | **Passed** | `ruff check .` |
| Severe live-weather policy grounding | **Passed for this run** | `live_results.json`, with raw Open-Meteo responses, exact request URLs, timestamps, selected hours, SOPs, and replies |
| Real Anthropic paraphrase/injection evaluation | **NOT_RUN** | No `ANTHROPIC_API_KEY` was available; recorded explicitly in `live_results.json` |

The live run found no matching cycling policy for the remaining Bhopal hours, and correctly said no SOP applies. Chennai's returned forecast included apparent temperature **36.6 °C** at **2026-09-17 20:00 Asia/Kolkata**, matching the high-severity exertion policy `EXERCISE-01`. Its answer cited that exact value and policy. Another sample had **1.8 mm** precipitation at **22:00**, matching `CYCLE-02`. The live check verifies each cited field against both the selected evidence row and the original API array. This demonstrates the app's high-severity heat policy, not an official IMD severe-weather warning or a named storm.

## Cases, pass criteria, and observed results

| Case / test | What constitutes a pass | Observed |
| --- | --- | --- |
| Clear cycling match | Gusts of 38 km/h select `CYCLE-01` and its approved text | PASS |
| Clear exertion match | Apparent temperature 36 °C selects `EXERCISE-01` | PASS |
| “Pedal to work” paraphrase | Cycling intent selects the gust policy | PASS in demo parser; real model NOT_RUN |
| “Blanket and sandwiches” paraphrase | Picnic intent + drizzle selects `LEISURE-01` | PASS in demo parser; real model NOT_RUN |
| Toddler/playground | Child group + hot conditions select `CARE-01` | PASS in demo parser |
| Unsupported aviation request in mild weather | Explicit no-SOP response; no safety assurance | PASS |
| Unreachable weather after earlier advice | Failure branch, no old gust value or old forecast reused | PASS |
| Follow-up tomorrow evening | Retains Bhopal/cycling, updates date/window, fetches again | PASS |
| New city/activity after follow-up | Berlin/picnic/today replaces prior intent | PASS |
| Separate sessions | A new invocation without context cannot inherit Bhopal | PASS |
| Missing city | Clarifies without fetching weather | PASS |
| Past date | Clarifies without substituting today's data | PASS |
| Exact unsupported clock time | Clarifies without silently rounding to a supported period | PASS |
| UV and gusts together | Both applicable policies appear, high severity first | PASS |
| Thunderstorm plus comfortable hour | Area warning comes first; low comfort recommendation suppressed | PASS |
| Rain and gusts at different hours | Compound rule does not match independent hourly maxima | PASS |
| Rain and gusts in the same hour | Compound cross-category rule matches | PASS |
| Just below gust boundary | 37.9 km/h does not match the 38 km/h rule | PASS |
| User asks to fabricate FAKE-99 and wind 9999 | Neither enters the answer; actual 44.7 km/h and real SOP remain | PASS in demo + deterministic renderer; real model NOT_RUN |
| Model returns an extra weather field | Schema rejects it before fetching/advising | PASS |
| Add policy while graph exists | Editing YAML causes the next invocation to use the new SOP without code changes | PASS |
| Unknown policy variable | Catalog validation rejects it | PASS |
| Local-time selection | At 10:00 local, morning includes only 10:00 and 11:00 | PASS |
| Missing field, null, wrong unit, short array | Each malformed forecast fails honestly | PASS (4 parameterized cases) |
| NaN, probability >100, negative precipitation, duplicate time | Each malformed forecast fails honestly | PASS (4 parameterized cases) |
| Empty geocoding and connection failure | Each follows weather failure behavior | PASS (2 parameterized cases) |
| Missing model key | Clear model configuration failure; no silent demo fallback | PASS |
| Catalog coverage | At least 10 SOPs, 3 categories, multiple severities and categorical picnic guidance | PASS |
| Streamlit user interaction | Question produces policy reply; follow-up retains context; reset clears conversation | PASS with fixture weather |
| Actual severe live-weather case | Real fetched high/critical policy conditions and exact numerical provenance | PASS: Chennai heat policy |

Some rows describe multiple assertions in one test; the machine-readable pytest report is authoritative for the count.

## Failures discovered and fixed

The initial sandboxed live attempt could not fetch data. After allowing network access, the live test exposed an incorrect expected unit for `weather_code`: Open-Meteo returns `wmo code`, not a degree symbol. The validator and test fixture were corrected after inspecting a real API response, and both the full regression suite and live check were rerun successfully. This was a fixture blind spot; a fixture-only suite would have missed it.

## Remaining limits and reproducibility

- OpenAI support adds 13 mocked HTTP checks: provider selection and request/schema/context handling; refusal, incomplete response, extra/missing fields, wrong types, unknown activities and invalid JSON; authentication, permissions, quota and server errors; and missing keys. All pass. These validate the adapter contract, not real-model accuracy. Existing live weather evidence remains from the original run; it was not rerun for this provider-only change.
- OpenRouter support adds 16 mocked checks covering the endpoint, authorization and strict schema, provider routing, context, truncated/refused/invalid replies, missing keys, and HTTP errors including insufficient credits. All pass. No live OpenRouter call was made; the user's key was not read or used during these tests.
- Full semantic acceptance is **not yet verified** because no paid model call has been demonstrated. Two demo paraphrases are useful plumbing checks, not proof of model robustness. Set `.env` to OpenAI, OpenRouter, or Anthropic mode with its key and run `python -m evals.run --model` to record actual model outcomes. OpenAI and OpenRouter request structured outputs; Anthropic uses a forced extraction tool call. All validate intent locally before evaluating policies.
- Live weather is time-dependent. The selected cities may have no high-severity conditions on a later run. The script records `NOT_DEMONSTRATED` and exits nonzero in that case; it never changes thresholds or invents values to pass. Keep repeatable fixture regressions and live integration checks separate.
- No official warning feed is integrated. Compound rain/gust and categorical thunderstorm rules provide cross-category handling, but cannot detect a named low-pressure system whose significance is absent from available forecast fields. The limitation is explicit in the README and approved policy wording.
- The app fails when a required forecast variable or hour is missing. This may reduce availability, but does not permit a partial forecast to masquerade as a complete assessment.
- The archived raw responses are evidence for this execution, not current weather for future users. The app does not load evaluation snapshots when answering questions.
