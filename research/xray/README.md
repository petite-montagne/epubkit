# X-Ray cast research scripts (delta7)

Research copies of the scripts behind the X-Ray cast list experiments. They are not part
of the epubkit package yet; the port into epubkit is a separate change. Book text, answer
keys (`*.tsv`) and run outputs (`*.cast.txt`, logs) are deliberately **not** included.

## Files

| File | What it is |
|---|---|
| `delta7.py` | The delta7 cast builder: sweeps each part for people, asks the model about them, merges name pairs, checks claims against the text. Runs live or replays a saved log. |
| `cards.py` | Step 1 quote cards (no model) plus the shared name helpers `low`, `same`, `common_words` that `delta7.py`, `fill.py` and `gaps.py` import. |
| `fill.py` | Adds step 1 cards for people a delta list never listed (a card never replaces an entry). |
| `gaps.py` | Voted list as is, plus delta rows only for people it lacks (optionally alias-aware). |
| `score.py` | Deterministic scorer: grades a `*.cast.txt` report against an answer key (right / thin / wrong / missing, junk, duplicates, spoilers). |
| `run-delta7.sh` | The delta7 live chain used for testing: PJ6 twice (repeatability), then HP 2 and DCC 4. |
| `watch.sh` | Watchdog: stops the chain's process group if free RAM drops under 4 GB or a game starts. |
| `patches/*.py` | The patch scripts that produced each version: delta5 → 6 → 6b → 6c → 7. History only; `delta7.py` is the result. |

## Running delta7

Paths assume the test layout under `~/cast-pilot` (epubkit source at
`~/cast-pilot/xray/epubkit/src`, these scripts in `~/cast-pilot/xray`). From `~/cast-pilot`:

```sh
export OPENAI_API_KEY=...   # the llama-server key; read from the environment only (LLAMA_KEY also works)
nice -n 10 ~/epubkit-venv/bin/python -I xray/delta7.py <book> OUT.cast.txt live
```

`<book>` is one of `dcc4`, `dcc5`, `pj6`, `hp1`, `hp2` (see `BOOK` in `delta7.py`).
Pass a saved request log instead of `live` to replay a run without the model.

Score a result:

```sh
python3 -I xray/score.py OUT.cast.txt KEY.tsv [--rules dcc5|hp1] [-v]
```

## Model request options

`delta7.py` talks to the local llama-server (`http://localhost:8081`, OpenAI-compatible API)
through epubkit's `OpenAIProvider`. Every request sends, for repeatable output:

- `temperature`: 0
- `seed`: 7
- `top_k`: 1
- `cache_prompt`: false
- `max_tokens`: 2000 (timeout 600 s)

Two PJ6 runs with these settings produced identical lists.
