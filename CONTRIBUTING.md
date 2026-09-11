# Contributing to ReMeta

Thanks for considering a contribution. Bug reports, validation datasets, and
code are all welcome.

## Getting set up

```bash
git clone https://github.com/guthib241/ReMeta.git
cd ReMeta
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e .
python -m unittest discover
```

There is nothing else to install. Run the test suite before every pull
request, and add `-v` if you want to see the test names.

## The bar

ReMeta produces numbers that could inform clinical decisions. That sets the
standard a little higher than for most small open-source projects.

**Any change to the statistics must come with a validation case** — a published
meta-analysis with known results that the change reproduces. Not a unit test
comparing our output to our output. An external reference.

## Rules

1. **No dependencies.** Standard library only, enforced in CI. ReMeta must run
   in a hospital, a library, and an air-gapped CI box.
2. **No language model in the calculation path.** Extraction may eventually use
   one; pooling never will. The output must be checkable by hand.
3. **Never silently change an estimator.** The reproduction gate exists because
   method-matching is the whole point. If you add an estimator, add it as an
   option and leave the default alone.
4. **State limitations in the docs, not just the code.** A tool like this is more
   dangerous when it is trusted beyond what it validates. If your change
   narrows or widens what ReMeta can honestly claim, update
   [docs/VALIDATION.md](docs/VALIDATION.md) in the same pull request.
5. **Error messages are for researchers, not Python developers.** Say what is
   wrong with which record, and where practical how to fix it. Every input
   problem should surface as a `DataError`, never a traceback.
6. **Keep the public API small.** Everything exported from `remeta` is a promise.
7. **Never compute a measure from inputs that cannot produce it.** Returning a
   different quantity than the one requested is the worst bug available here,
   because the output looks right. Refuse, and say which field to supply.
8. **Every number in a public document needs an entry in
   [CLAIMS.md](CLAIMS.md).** Continuous integration fails otherwise. Give a
   source as a DOI plus a location in the paper, or the test that proves it.
9. **Write the failing test first**, commit it, then the fix. If a change alters
   a behaviour an existing test asserts, say so in the commit message: that is
   the difference between a specification change and a moved goalpost.

## Style

- Match the surrounding code. Type hints on public functions, docstrings that
  explain *why* rather than restating the signature.
- Keep the CLI's human-readable output stable where you can; people paste it
  into issues and reports.
- No new files unless they carry their weight.

## Most valuable contribution right now

**Digitised forest plots from published meta-analyses that included retracted
studies**, especially from the Graña Possamai et al. 2025 dataset. The pooling
engine is validated. The impact-classification validation set is what is
missing, and it is the thing that decides whether this project is real. See
[docs/VALIDATION.md](docs/VALIDATION.md) for the pass and fail criteria.

One JSON file per meta-analysis, under `data/`, with `reported_estimate`
filled in from the paper so the reproduction gate can check it. Include the
source DOI in `source_doi`, and say in `metadata` where the numbers came from
(table, figure, supplement) and whether they were read off a plot.

Real trial data goes in `data/`. Synthetic fixtures go in `data/examples/`,
and every one of them must be labelled synthetic in its `metadata` and have a
test asserting that it demonstrates the severity class its name claims.

## Reporting a wrong answer

If ReMeta disagrees with a published recalculation, that is the most useful
bug report available. Open an issue with:

- the meta-analysis and its source,
- the published numbers,
- the JSON input you used,
- ReMeta's output (`remeta check yourfile.json --json` is ideal).

Do not assume the paper is right — but do not assume we are either.

## Reporting a security issue

ReMeta parses untrusted JSON and nothing else: it opens no network
connections, executes no input, and writes no files. If you find something
that contradicts that, please open an issue.

## License

Contributions are accepted under the [MIT License](LICENSE), the same terms as
the rest of the project.
