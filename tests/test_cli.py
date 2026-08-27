"""The command-line contract: exit codes and stderr, which CI reads.

Zero means the run completed and every metric held. Anything else means the table
on stdout, if there is one, must not be trusted. These tests cover the paths that
cannot be reached by breaking the machine -- an absent Finnish dictionary, in
particular, cannot be simulated by hiding the system package
(`VOIKKO_DICTIONARY_PATH` adds a search path rather than replacing it).
"""

from __future__ import annotations

import pytest

from fi_rag_eval import cli, db
from fi_rag_eval.analyse import AnalyserError, Morphology


def test_a_missing_dictionary_fails_loudly_instead_of_scoring_raw_tokens(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The full contract, composed: a helpful message on **stderr**, a non-zero
    exit, and nothing resembling a metric table on stdout.

    Without this the harness would analyse every word as its raw surface token,
    score the lemma cells against a worse-than-snowball index, and publish that
    under the label "lemmatisation". A number computed by a silently degraded
    analyser is the worst output this project can produce.
    """

    def refuse() -> None:
        raise AnalyserError("the Finnish analyser opened but analyses nothing")

    monkeypatch.setattr(Morphology, "open", staticmethod(refuse))
    assert cli.main(["eval"]) == 1

    captured = capsys.readouterr()
    assert captured.out == "", "no table may be printed when the analyser is unusable"
    assert "analyses nothing" in captured.err
    assert captured.err.startswith("fi-rag-eval eval:")


def test_the_analyser_is_opened_before_the_database_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Order matters for the message the user actually sees.

    A machine missing the dictionary is usually a machine that has just cloned the
    repo, so it will often also have no corpus loaded. Opening the analyser first
    means it reports the fix it can name rather than an empty-corpus error that
    sends the reader to the wrong problem.
    """
    touched: list[str] = []

    def refuse() -> None:
        touched.append("analyser")
        raise AnalyserError("no dictionary")

    def connect(*args: object, **kwargs: object) -> None:
        touched.append("database")
        raise AssertionError("the database must not be reached first")

    monkeypatch.setattr(Morphology, "open", staticmethod(refuse))
    monkeypatch.setattr(db, "connect", connect)
    assert cli.main(["eval"]) == 1
    assert touched == ["analyser"]


def test_an_unknown_command_is_argparses_problem_not_a_traceback() -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["measure-vibes"])
    assert raised.value.code == 2
