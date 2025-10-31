from __future__ import annotations

from pathlib import Path

from scripts import asr_mic_tester


def test_mic_test_output_duplicates_stdout(monkeypatch, tmp_path, capsys) -> None:
    log_path = tmp_path / "logs" / "mic_test.log"
    monkeypatch.setenv("MIC_TEST_OUTPUT", str(log_path))

    with asr_mic_tester._tee_stdout_from_env():
        print("hello mic test")

    monkeypatch.delenv("MIC_TEST_OUTPUT", raising=False)
    captured = capsys.readouterr()

    assert "hello mic test" in captured.out
    assert log_path.exists()
    assert "hello mic test" in log_path.read_text(encoding="utf-8")
    assert log_path.parent == Path(tmp_path / "logs")
