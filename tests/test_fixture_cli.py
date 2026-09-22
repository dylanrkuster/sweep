import subprocess
import sys


def test_fixture_command_works_outside_the_repository(sample_dir, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sweep.testing",
            "--messages",
            str(sample_dir / "messages.jsonl"),
            "--cases",
            str(sample_dir / "cases.jsonl"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "5 messages and 3 cases" in result.stdout
    assert "3 decision inputs with 1 prior-message references" in result.stdout
    assert "no model predictions or mailbox changes" in result.stdout
    assert "receipt.pdf" not in result.stdout
    assert result.stderr == ""


def test_fixture_command_fails_clearly_without_echoing_invalid_data(
    message_record, case_record, write_jsonl, tmp_path
):
    marker = "PRIVATE-SYNTHETIC-CONTENT-DO-NOT-ECHO"
    case_record["expected_action"] = marker
    messages_path = write_jsonl([message_record], "messages.jsonl")
    cases_path = write_jsonl([case_record], "cases.jsonl")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sweep.testing",
            "--messages",
            str(messages_path),
            "--cases",
            str(cases_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert f"{cases_path}:1:" in result.stderr
    assert marker not in result.stderr
    assert result.stdout == ""
